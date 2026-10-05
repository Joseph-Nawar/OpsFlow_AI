"""The narrow idempotent sale-order entry point used by OpsFlow."""

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare
from psycopg2 import IntegrityError

_MAX_ID = 2_147_483_647
_UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_REJECTED_CODES = {
    "INTEGRATION_CONFIG",
    "TRUSTED_CUSTOMER_MISSING",
    "TRUSTED_CUSTOMER_AMBIGUOUS",
    "TRUSTED_PRODUCT_MISSING",
    "TRUSTED_PRODUCT_CHANGED",
    "INVENTORY_INSUFFICIENT",
    "PROVIDER_REJECTED",
}


class _BridgeInputError(ValueError):
    """A bounded malformed bridge input without provider-controlled detail."""


class SaleOrder(models.Model):
    _inherit = "sale.order"

    opsflow_order_id = fields.Char(
        size=36,
        index=True,
        copy=False,
        readonly=True,
    )

    _opsflow_order_id_unique = models.Constraint(
        "UNIQUE(opsflow_order_id)",
        "An OpsFlow order can have only one Odoo sales order.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if any("opsflow_order_id" in values for values in vals_list):
            raise AccessError(_("The OpsFlow order identity is assigned only by its bridge."))
        return super().create(vals_list)

    def write(self, values):
        if "opsflow_order_id" in values and any(
            order.opsflow_order_id != values["opsflow_order_id"] for order in self
        ):
            raise AccessError(_("The OpsFlow order identity is immutable."))
        return super().write(values)

    @api.model
    def opsflow_create_or_get_sale_order(
        self,
        opsflow_order_id: str,
        company_id: int,
        warehouse_id: int,
        pricelist_id: int,
        currency_id: int,
        partner_id: int,
        customer_reference: str,
        client_order_ref: str,
        requested_delivery_date: str | None,
        lines: list[dict[str, object]],
        **unexpected: object,
    ) -> dict[str, object]:
        """Atomically reconcile, create and confirm one order for a stable UUID."""

        user = self.env.user
        if not user.has_group("opsflow_sale_bridge.group_opsflow_sale_bridge"):
            return _rejected("INTEGRATION_CONFIG")
        if unexpected:
            return _rejected("PROVIDER_REJECTED")
        try:
            payload = _normalize_payload(
                opsflow_order_id=opsflow_order_id,
                company_id=company_id,
                warehouse_id=warehouse_id,
                pricelist_id=pricelist_id,
                currency_id=currency_id,
                partner_id=partner_id,
                customer_reference=customer_reference,
                client_order_ref=client_order_ref,
                requested_delivery_date=requested_delivery_date,
                lines=lines,
            )
        except _BridgeInputError:
            return _rejected("PROVIDER_REJECTED")

        if payload["company_id"] not in user.company_ids.ids:
            return _rejected("INTEGRATION_CONFIG")

        # JSON-2 accepts caller-supplied context separately from method kwargs.
        # Replace it after authorization instead of trusting any incoming scope.
        bridge = self.with_context(
            {},
            allowed_company_ids=[payload["company_id"]],
            warehouse=payload["warehouse_id"],
        )
        existing = bridge.search([("opsflow_order_id", "=", payload["opsflow_order_id"])], limit=2)
        if len(existing) > 1:
            return _reconciliation_required()
        if existing:
            return bridge._opsflow_existing_receipt(existing, payload)

        rejection = bridge._opsflow_recheck_before_create(payload)
        if rejection is not None:
            return _rejected(rejection)

        try:
            with bridge.env.cr.savepoint():
                order = bridge._opsflow_create_confirmed_order(payload)
                order.flush_recordset(["opsflow_order_id", "state", "order_line"])
        except IntegrityError as error:
            if (
                getattr(getattr(error, "diag", None), "constraint_name", None)
                != "sale_order_opsflow_order_id_unique"
            ):
                raise
            # Odoo 19 uses REPEATABLE READ. The conflicting insert proves a
            # concurrent transaction committed the unique UUID, but this
            # request's earlier snapshot may not see it. A fresh JSON-2
            # invocation will reconcile the winner with the same identity.
            return _concurrency_retry()

        if order.state != "sale":
            raise UserError(_("The OpsFlow sales order was not confirmed."))
        return _receipt("created", order)

    def _opsflow_existing_receipt(self, order, payload):
        if not self._opsflow_payload_matches(order, payload):
            return _conflict()
        if order.state != "sale":
            return _reconciliation_required()
        return _receipt("replayed", order)

    def _opsflow_payload_matches(self, order, payload):
        if (
            order.opsflow_order_id != payload["opsflow_order_id"]
            or order.partner_id.id != payload["partner_id"]
            or order.partner_id.ref != payload["customer_reference"]
            or order.company_id.id != payload["company_id"]
            or order.warehouse_id.id != payload["warehouse_id"]
            or order.pricelist_id.id != payload["pricelist_id"]
            or order.currency_id.id != payload["currency_id"]
            or order.client_order_ref != payload["client_order_ref"]
        ):
            return False
        expected_date = payload["commitment_date"]
        actual_date = (
            fields.Datetime.to_datetime(order.commitment_date) if order.commitment_date else None
        )
        if actual_date != expected_date:
            return False

        actual_lines = order.order_line.filtered(lambda line: not line.display_type).sorted(
            key=lambda line: (line.sequence, line.id)
        )
        requested_lines = payload["lines"]
        if len(actual_lines) != len(requested_lines):
            return False
        for actual, expected in zip(actual_lines, requested_lines, strict=True):
            if (
                actual.sequence != expected["sequence"]
                or actual.product_id.id != expected["product_id"]
                or actual.product_id.default_code != expected["sku"]
                or actual.product_uom_id.id != expected["uom_id"]
            ):
                return False
            if (
                float_compare(
                    actual.product_uom_qty,
                    float(expected["quantity"]),
                    precision_rounding=actual.product_uom_id.rounding,
                )
                != 0
            ):
                return False
            if (
                float_compare(
                    actual.price_unit,
                    float(expected["submitted_price"]),
                    precision_rounding=order.currency_id.rounding,
                )
                != 0
            ):
                return False
        return True

    def _opsflow_recheck_before_create(self, payload):
        company = self.env["res.company"].browse(payload["company_id"]).exists()
        if not company or not company.active or company.currency_id.id != payload["currency_id"]:
            return "INTEGRATION_CONFIG"

        warehouse = self.env["stock.warehouse"].browse(payload["warehouse_id"]).exists()
        if not warehouse or warehouse.company_id.id != company.id or not warehouse.lot_stock_id:
            return "INTEGRATION_CONFIG"

        pricelist = self.env["product.pricelist"].browse(payload["pricelist_id"]).exists()
        if (
            not pricelist
            or pricelist.company_id.id not in (False, company.id)
            or pricelist.currency_id.id != payload["currency_id"]
            or self.env["product.pricelist.item"].search_count(
                [("pricelist_id", "=", pricelist.id)]
            )
        ):
            return "INTEGRATION_CONFIG"

        partner = self.env["res.partner"].browse(payload["partner_id"]).exists()
        if not partner:
            return "TRUSTED_CUSTOMER_MISSING"
        if (
            partner.ref != payload["customer_reference"]
            or not partner.active
            or not partner.is_company
            or partner.customer_rank <= 0
            or partner.company_id.id not in (False, company.id)
        ):
            return "TRUSTED_CUSTOMER_MISSING"

        requested_by_product = {}
        checked_products = {}
        for line in payload["lines"]:
            product = self.env["product.product"].browse(line["product_id"]).exists()
            if not product:
                return "TRUSTED_PRODUCT_MISSING"
            if (
                product.default_code != line["sku"]
                or not product.active
                or not product.sale_ok
                or not product.is_storable
                or product.company_id.id not in (False, company.id)
            ):
                return "TRUSTED_PRODUCT_CHANGED"
            if product.currency_id.id != payload["currency_id"]:
                return "TRUSTED_PRODUCT_CHANGED"
            if product.uom_id.id != line["uom_id"]:
                return "TRUSTED_PRODUCT_CHANGED"
            currency = product.currency_id
            if (
                float_compare(
                    product.with_company(company).lst_price,
                    float(line["expected_lst_price"]),
                    precision_rounding=currency.rounding,
                )
                != 0
            ):
                return "TRUSTED_PRODUCT_CHANGED"
            requested_by_product[product.id] = (
                requested_by_product.get(product.id, Decimal("0")) + line["quantity"]
            )
            checked_products[product.id] = product

        for product_id, quantity in requested_by_product.items():
            product = (
                checked_products[product_id]
                .with_company(company)
                .with_context(allowed_company_ids=[company.id], warehouse=warehouse.id)
            )
            if (
                float_compare(
                    product.free_qty,
                    float(quantity),
                    precision_rounding=product.uom_id.rounding,
                )
                < 0
            ):
                return "INVENTORY_INSUFFICIENT"
        return None

    def _opsflow_create_confirmed_order(self, payload):
        order_values = {
            "opsflow_order_id": payload["opsflow_order_id"],
            "company_id": payload["company_id"],
            "warehouse_id": payload["warehouse_id"],
            "pricelist_id": payload["pricelist_id"],
            "partner_id": payload["partner_id"],
            "client_order_ref": payload["client_order_ref"],
            "commitment_date": (
                fields.Datetime.to_string(payload["commitment_date"])
                if payload["commitment_date"] is not None
                else False
            ),
            "order_line": [
                Command.create(
                    {
                        "sequence": line["sequence"],
                        "product_id": line["product_id"],
                        "product_uom_id": line["uom_id"],
                        "product_uom_qty": float(line["quantity"]),
                        "price_unit": float(line["submitted_price"]),
                        "name": line["description"]
                        or self.env["product.product"].browse(line["product_id"]).name,
                    }
                )
                for line in payload["lines"]
            ],
        }
        order = super().create(order_values)
        order.action_confirm()
        return order


def _normalize_payload(
    *,
    opsflow_order_id,
    company_id,
    warehouse_id,
    pricelist_id,
    currency_id,
    partner_id,
    customer_reference,
    client_order_ref,
    requested_delivery_date,
    lines,
):
    if (
        type(opsflow_order_id) is not str
        or _UUID_PATTERN.fullmatch(opsflow_order_id) is None
        or str(UUID(opsflow_order_id)) != opsflow_order_id
    ):
        raise _BridgeInputError
    for value in (company_id, warehouse_id, pricelist_id, currency_id, partner_id):
        _validate_id(value)
    customer_reference = _validate_string(customer_reference, 256)
    client_order_ref = _validate_string(client_order_ref, 256)
    if requested_delivery_date is None:
        commitment_date = None
    else:
        if type(requested_delivery_date) is not str or len(requested_delivery_date) != 10:
            raise _BridgeInputError
        try:
            parsed_date = date.fromisoformat(requested_delivery_date)
        except ValueError:
            raise _BridgeInputError from None
        if parsed_date.isoformat() != requested_delivery_date:
            raise _BridgeInputError
        commitment_date = datetime.combine(parsed_date, time.min)
    if type(lines) is not list or not 1 <= len(lines) <= 100:
        raise _BridgeInputError

    normalized_lines = []
    for expected_sequence, line in enumerate(lines, start=1):
        if type(line) is not dict:
            raise _BridgeInputError
        allowed_keys = {
            "sequence",
            "product_id",
            "sku",
            "uom_id",
            "quantity",
            "submitted_price",
            "expected_lst_price",
            "description",
        }
        required_keys = allowed_keys - {"description"}
        if not required_keys.issubset(line) or not set(line).issubset(allowed_keys):
            raise _BridgeInputError
        sequence = line["sequence"]
        if type(sequence) is not int or sequence != expected_sequence or sequence > 100:
            raise _BridgeInputError
        _validate_id(line["product_id"])
        sku = _validate_string(line["sku"], 256)
        _validate_id(line["uom_id"])
        quantity = _validate_decimal(line["quantity"], positive=True)
        submitted_price = _validate_decimal(line["submitted_price"])
        expected_lst_price = _validate_decimal(line["expected_lst_price"])
        description = line.get("description")
        if "description" in line and (type(description) is not str or len(description) > 512):
            raise _BridgeInputError
        normalized_lines.append(
            {
                "sequence": sequence,
                "product_id": line["product_id"],
                "sku": sku,
                "uom_id": line["uom_id"],
                "quantity": quantity,
                "submitted_price": submitted_price,
                "expected_lst_price": expected_lst_price,
                "description": description,
            }
        )
    return {
        "opsflow_order_id": opsflow_order_id,
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "pricelist_id": pricelist_id,
        "currency_id": currency_id,
        "partner_id": partner_id,
        "customer_reference": customer_reference,
        "client_order_ref": client_order_ref,
        "commitment_date": commitment_date,
        "lines": tuple(normalized_lines),
    }


def _validate_id(value):
    if type(value) is not int or not 1 <= value <= _MAX_ID:
        raise _BridgeInputError


def _validate_string(value, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise _BridgeInputError
    return value


def _validate_decimal(value, *, positive=False):
    if type(value) is not str or len(value) > 64 or _DECIMAL_PATTERN.fullmatch(value) is None:
        raise _BridgeInputError
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise _BridgeInputError from None
    if not parsed.is_finite() or parsed < 0 or (positive and parsed == 0):
        raise _BridgeInputError
    return parsed


def _rejected(code):
    if code not in _REJECTED_CODES:
        code = "PROVIDER_REJECTED"
    return {"outcome": "rejected", "failure_code": code}


def _conflict():
    return {"outcome": "conflict", "failure_code": "IDEMPOTENCY_CONFLICT"}


def _reconciliation_required():
    return {"outcome": "reconciliation_required", "failure_code": "RECONCILIATION_REQUIRED"}


def _concurrency_retry():
    return {"outcome": "concurrency_retry"}


def _receipt(outcome, order):
    return {
        "outcome": outcome,
        "opsflow_order_id": order.opsflow_order_id,
        "sale_order_id": order.id,
        "sale_order_name": order.name,
        "confirmed_state": order.state,
    }
