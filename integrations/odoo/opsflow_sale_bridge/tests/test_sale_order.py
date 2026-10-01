"""Database-backed tests for the small OpsFlow sale-order bridge."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from psycopg2.errors import UniqueViolation

from ..models.sale_order import _normalize_payload


@tagged("post_install", "-at_install")
class TestSaleOrderOpsflowBridge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.pricelist = cls.env["product.pricelist"].create(
            {
                "name": "OpsFlow M9C Test Pricelist",
                "company_id": cls.company.id,
                "currency_id": cls.currency.id,
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "OpsFlow Synthetic Customer",
                "ref": "M9C-CUSTOMER-001",
                "is_company": True,
                "customer_rank": 1,
            }
        )
        cls.template = cls.env["product.template"].create(
            {
                "name": "OpsFlow Synthetic Product",
                "default_code": "M9C-SKU-001",
                "type": "consu",
                "is_storable": True,
                "list_price": 10.0,
                "company_id": cls.company.id,
            }
        )
        cls.product = cls.template.product_variant_id
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 10.0
        )
        cls.bridge_group = cls.env.ref("opsflow_sale_bridge.group_opsflow_sale_bridge")
        cls.user_group_ids = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("sales_team.group_sale_salesman").id,
            cls.env.ref("stock.group_stock_user").id,
            cls.bridge_group.id,
        ]
        cls.integration_user = cls.env["res.users"].create(
            {
                "name": "OpsFlow Disposable Bot",
                "login": "opsflow-m9c-bot@example.test",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set(cls.user_group_ids)],
            }
        )
        cls.ordinary_sales_user = cls.env["res.users"].create(
            {
                "name": "OpsFlow Ordinary Sales User",
                "login": "opsflow-m9c-ordinary@example.test",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set(cls.user_group_ids[:-1])],
            }
        )

    def _payload(self, order_id=None):
        return {
            "opsflow_order_id": str(order_id or uuid4()),
            "company_id": self.company.id,
            "warehouse_id": self.warehouse.id,
            "pricelist_id": self.pricelist.id,
            "currency_id": self.currency.id,
            "partner_id": self.customer.id,
            "customer_reference": "M9C-CUSTOMER-001",
            "client_order_ref": "M9C-PO-001",
            "requested_delivery_date": "2026-10-30",
            "lines": [
                {
                    "sequence": 1,
                    "product_id": self.product.id,
                    "sku": "M9C-SKU-001",
                    "uom_id": self.product.uom_id.id,
                    "quantity": "2",
                    "submitted_price": "10.25",
                    "expected_lst_price": format(Decimal(str(self.product.lst_price)), "f"),
                    "description": "Approved OpsFlow line",
                }
            ],
        }

    def _bridge(self, payload, user=None):
        bridge = self.env["sale.order"].with_user(user or self.integration_user)
        return bridge.opsflow_create_or_get_sale_order(**payload)

    def test_bridge_returns_one_confirmed_order_for_same_opsflow_identity(self):
        payload = self._payload()

        created = self._bridge(payload)
        replayed = self._bridge(payload)

        self.assertEqual(created["outcome"], "created")
        self.assertEqual(replayed["outcome"], "replayed")
        self.assertEqual(created["sale_order_id"], replayed["sale_order_id"])
        self.assertEqual(created["sale_order_name"], replayed["sale_order_name"])
        self.assertEqual(created["confirmed_state"], "sale")
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("opsflow_order_id", "=", payload["opsflow_order_id"])]
            ),
            1,
        )
        order = self.env["sale.order"].browse(created["sale_order_id"])
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.order_line.price_unit, 10.25)

    def test_opsflow_order_id_is_immutable_and_unique(self):
        payload = self._payload()
        receipt = self._bridge(payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])

        with self.assertRaises(AccessError):
            self.env["sale.order"].create(
                {
                    "partner_id": self.customer.id,
                    "opsflow_order_id": payload["opsflow_order_id"],
                }
            )
        with self.assertRaises(AccessError):
            order.write({"opsflow_order_id": str(uuid4())})
        with self.assertRaises(AccessError):
            order.write({"opsflow_order_id": False})

        other = self.env["sale.order"].create({"partner_id": self.customer.id})
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.env.cr.execute(
                "UPDATE sale_order SET opsflow_order_id = %s WHERE id = %s",
                (payload["opsflow_order_id"], other.id),
            )

    def test_existing_identity_with_different_payload_is_rejected(self):
        payload = self._payload()
        receipt = self._bridge(payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])
        old_po = order.client_order_ref

        changed = dict(payload, client_order_ref="M9C-PO-DIFFERENT")
        outcome = self._bridge(changed)

        self.assertEqual(outcome, {"outcome": "conflict", "failure_code": "IDEMPOTENCY_CONFLICT"})
        self.assertEqual(order.client_order_ref, old_po)
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("opsflow_order_id", "=", payload["opsflow_order_id"])]
            ),
            1,
        )

    def test_replay_rejects_changed_optional_delivery_date(self):
        payload = self._payload()
        receipt = self._bridge(payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])

        changed = dict(payload, requested_delivery_date=None)
        outcome = self._bridge(changed)

        self.assertEqual(
            outcome,
            {"outcome": "conflict", "failure_code": "IDEMPOTENCY_CONFLICT"},
        )
        self.assertEqual(order.commitment_date, datetime(2026, 10, 30))
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("opsflow_order_id", "=", payload["opsflow_order_id"])]
            ),
            1,
        )

    def test_replay_compares_stable_header_and_line_fields(self):
        payload = self._payload()
        receipt = self._bridge(payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])
        normalized = _normalize_payload(**payload)
        line = normalized["lines"][0]
        cases = (
            {**normalized, "opsflow_order_id": str(uuid4())},
            {**normalized, "partner_id": self.customer.id + 1},
            {**normalized, "customer_reference": "M9C-CUSTOMER-OTHER"},
            {**normalized, "company_id": self.company.id + 1},
            {**normalized, "warehouse_id": self.warehouse.id + 1},
            {**normalized, "pricelist_id": self.pricelist.id + 1},
            {**normalized, "currency_id": self.currency.id + 1},
            {**normalized, "client_order_ref": "M9C-PO-OTHER"},
            {**normalized, "commitment_date": None},
        )
        for field, value in (
            ("product_id", self.product.id + 1),
            ("sku", "M9C-SKU-OTHER"),
            ("quantity", line["quantity"] + Decimal("1")),
            ("uom_id", self.product.uom_id.id + 1),
            ("submitted_price", line["submitted_price"] + Decimal("1")),
            ("sequence", 2),
        ):
            cases += ({**normalized, "lines": ({**line, field: value},)},)
        cases += (
            {
                **normalized,
                "lines": ({**line}, {**line, "sequence": 2}),
            },
        )

        for changed in cases:
            self.assertFalse(self.env["sale.order"]._opsflow_payload_matches(order, changed))

        order.action_cancel()
        outcome = self._bridge(payload)
        self.assertEqual(
            outcome,
            {
                "outcome": "reconciliation_required",
                "failure_code": "RECONCILIATION_REQUIRED",
            },
        )

    def test_bridge_writes_submitted_price_not_recomputed_lst_price(self):
        attribute = self.env["product.attribute"].create(
            {"name": "OpsFlow Finish", "create_variant": "always"}
        )
        value = self.env["product.attribute.value"].create(
            {
                "name": "OpsFlow Polished",
                "attribute_id": attribute.id,
                "default_extra_price": 2.0,
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "OpsFlow Variant Product",
                "default_code": "M9C-SKU-VARIANT",
                "type": "consu",
                "is_storable": True,
                "list_price": 10.0,
                "company_id": self.company.id,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set([value.id])],
                        }
                    )
                ],
            }
        )
        product = template.product_variant_id
        self.env["stock.quant"]._update_available_quantity(
            product, self.warehouse.lot_stock_id, 5.0
        )
        self.assertAlmostEqual(product.lst_price, 12.0)

        payload = self._payload()
        payload["lines"] = [
            {
                "sequence": 1,
                "product_id": product.id,
                "sku": "M9C-SKU-VARIANT",
                "uom_id": product.uom_id.id,
                "quantity": "1",
                "submitted_price": "12.4",
                "expected_lst_price": "12.0",
            }
        ]
        receipt = self._bridge(payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])

        self.assertEqual(receipt["outcome"], "created")
        self.assertAlmostEqual(order.order_line.price_unit, 12.4)
        self.assertNotEqual(order.order_line.price_unit, product.lst_price)

    def test_confirmation_failure_rolls_back_new_order(self):
        payload = self._payload()
        sale_order_class = type(self.env["sale.order"])

        with (
            patch.object(sale_order_class, "action_confirm", side_effect=UserError("probe")),
            self.assertRaises(UserError),
        ):
            self._bridge(payload)
        self.assertFalse(
            self.env["sale.order"].search([("opsflow_order_id", "=", payload["opsflow_order_id"])])
        )

    def test_matching_replay_returns_same_confirmed_order(self):
        payload = self._payload()
        first = self._bridge(payload)
        second = self._bridge(payload)

        self.assertIn(first["outcome"], ("created", "replayed"))
        self.assertEqual(second["outcome"], "replayed")
        self.assertEqual(first["sale_order_id"], second["sale_order_id"])
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("opsflow_order_id", "=", payload["opsflow_order_id"])]
            ),
            1,
        )

    def test_final_recheck_rejects_changed_trusted_data_before_write(self):
        cases = (
            ("customer", "TRUSTED_CUSTOMER_MISSING"),
            ("product", "TRUSTED_PRODUCT_CHANGED"),
            ("price", "TRUSTED_PRODUCT_CHANGED"),
            ("uom", "TRUSTED_PRODUCT_CHANGED"),
            ("stock", "INVENTORY_INSUFFICIENT"),
        )
        for case, expected_code in cases:
            with self.subTest(case=case):
                payload = self._payload()
                if case == "customer":
                    self.customer.active = False
                elif case == "product":
                    self.product.sale_ok = False
                elif case == "price":
                    self.template.list_price = 11.0
                elif case == "uom":
                    payload["lines"][0]["uom_id"] = self.env.ref("uom.product_uom_dozen").id
                else:
                    payload["lines"][0]["quantity"] = "11"

                outcome = self._bridge(payload)

                self.assertEqual(
                    outcome,
                    {"outcome": "rejected", "failure_code": expected_code},
                )
                self.assertEqual(
                    self.env["sale.order"].search_count(
                        [("opsflow_order_id", "=", payload["opsflow_order_id"])]
                    ),
                    0,
                )

                if case == "customer":
                    self.customer.active = True
                elif case == "product":
                    self.product.sale_ok = True
                elif case == "price":
                    self.template.list_price = 10.0

    def test_forged_context_cannot_change_explicit_warehouse_scope(self):
        payload = self._payload()
        bridge = (
            self.env["sale.order"]
            .with_user(self.integration_user)
            .with_context(allowed_company_ids=[self.company.id], warehouse=2_147_483_647)
        )

        receipt = bridge.opsflow_create_or_get_sale_order(**payload)
        order = self.env["sale.order"].browse(receipt["sale_order_id"])

        self.assertEqual(receipt["outcome"], "created")
        self.assertEqual(order.company_id, self.company)
        self.assertEqual(order.warehouse_id, self.warehouse)

    def test_method_requires_bridge_group_and_allowed_company(self):
        payload = self._payload()
        created = self._bridge(payload)
        order = self.env["sale.order"].browse(created["sale_order_id"])
        old_po = order.client_order_ref

        outcome = self._bridge(payload, self.ordinary_sales_user)

        self.assertEqual(outcome, {"outcome": "rejected", "failure_code": "INTEGRATION_CONFIG"})
        self.assertEqual(order.client_order_ref, old_po)
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("opsflow_order_id", "=", payload["opsflow_order_id"])]
            ),
            1,
        )

        outside_company = self.env["res.company"].create({"name": "OpsFlow Out-of-Scope"})
        disallowed = self._payload()
        disallowed["company_id"] = outside_company.id
        outcome = self._bridge(disallowed)
        self.assertEqual(
            outcome,
            {"outcome": "rejected", "failure_code": "INTEGRATION_CONFIG"},
        )
        self.assertFalse(
            self.env["sale.order"].search(
                [("opsflow_order_id", "=", disallowed["opsflow_order_id"])]
            )
        )

    def test_public_method_rejects_malformed_or_extra_arguments(self):
        malformed = self._payload(order_id="NOT-A-CANONICAL-UUID")
        outcome = self._bridge(malformed)
        self.assertEqual(outcome, {"outcome": "rejected", "failure_code": "PROVIDER_REJECTED"})

        extra = self._payload()
        extra["arbitrary_model"] = "res.partner"
        outcome = self._bridge(extra)
        self.assertEqual(outcome, {"outcome": "rejected", "failure_code": "PROVIDER_REJECTED"})
