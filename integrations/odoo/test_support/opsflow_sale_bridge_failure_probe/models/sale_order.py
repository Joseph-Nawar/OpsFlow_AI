from threading import Barrier, Lock, local

from odoo import api, models
from odoo.exceptions import UserError

_ROLLBACK_PROBE_ORDER_ID = "00000000-0000-4000-8000-000000000009"
_NONCONFIRMING_PROBE_ORDER_ID = "00000000-0000-4000-8000-000000000010"
_RACE_PROBE_PREFIX = "M9C-TEST-RACE:"
_race_request = local()
_race_barriers: dict[str, Barrier] = {}
_race_barriers_lock = Lock()


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def opsflow_create_or_get_sale_order(
        self,
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
        **unexpected,
    ):
        if type(client_order_ref) is str and client_order_ref.startswith(_RACE_PROBE_PREFIX):
            _race_request.order_id = opsflow_order_id
        try:
            return super().opsflow_create_or_get_sale_order(
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
                **unexpected,
            )
        finally:
            if hasattr(_race_request, "order_id"):
                del _race_request.order_id

    @api.model
    def search(self, domain, offset=0, limit=None, order=None):
        records = super().search(domain, offset=offset, limit=limit, order=order)
        order_id = getattr(_race_request, "order_id", None)
        if (
            self._name == "sale.order"
            and limit == 2
            and not records
            and order_id is not None
            and _contains_order_identity(domain, order_id)
        ):
            with _race_barriers_lock:
                barrier = _race_barriers.setdefault(order_id, Barrier(2))
            barrier.wait(timeout=20)
        return records

    def action_confirm(self):
        if any(order.opsflow_order_id == _NONCONFIRMING_PROBE_ORDER_ID for order in self):
            return True
        if any(order.opsflow_order_id == _ROLLBACK_PROBE_ORDER_ID for order in self):
            raise UserError("OPSFlow disposable confirmation rollback probe")
        return super().action_confirm()


def _contains_order_identity(domain, order_id):
    return any(
        isinstance(term, (tuple, list))
        and len(term) == 3
        and term[0] == "opsflow_order_id"
        and term[1] == "="
        and term[2] == order_id
        for term in domain
    )
