from odoo import models
from odoo.exceptions import UserError

_ROLLBACK_PROBE_ORDER_ID = "00000000-0000-4000-8000-000000000009"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        if any(order.opsflow_order_id == _ROLLBACK_PROBE_ORDER_ID for order in self):
            raise UserError("OPSFlow disposable confirmation rollback probe")
        return super().action_confirm()
