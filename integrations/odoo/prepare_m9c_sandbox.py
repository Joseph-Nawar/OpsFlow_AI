"""Seed synthetic M9C/M9E records from an Odoo shell in a disposable database.

Run only with ``odoo shell`` and the three required OPSFLOW_M9C_* environment
variables documented in docs/development/odoo-m9c-sandbox.md. This helper is
not imported by OpsFlow or the production bridge addon.
"""

from __future__ import annotations

# ``env`` is injected by Odoo's ``odoo shell`` command.
# ruff: noqa: F821
import json
import os
import re
from pathlib import Path

from odoo import Command

database = os.environ.get("OPSFLOW_M9C_SANDBOX_DATABASE", "")
if env.cr.dbname != database or not re.fullmatch(r"opsflow_(?:m9c|m9e)_[a-z0-9_]+", database):
    raise RuntimeError("sandbox helper requires its exact disposable M9C/M9E database")
if not env.su:
    raise RuntimeError("sandbox helper must run in the Odoo superuser shell")

fixture_path = Path(os.environ.get("OPSFLOW_M9C_FIXTURE_PATH", ""))
api_key_path = Path(os.environ.get("OPSFLOW_M9C_API_KEY_PATH", ""))
result_path = Path(os.environ.get("OPSFLOW_M9C_RESULT_PATH", ""))
if not all(str(path).startswith("/tmp/") for path in (fixture_path, api_key_path, result_path)):
    raise RuntimeError("sandbox input/output files must be under /tmp")

fixture = json.loads(fixture_path.read_text())
suffix = fixture.get("suffix")
customer_reference = fixture.get("customer_reference")
sku = fixture.get("sku")
if not isinstance(suffix, str) or not re.fullmatch(r"[A-Z0-9]{8,16}", suffix):
    raise RuntimeError("fixture suffix must be an uppercase synthetic identifier")
if customer_reference != f"OPSFLOW-M9E-CUST-{suffix}":
    raise RuntimeError("fixture must use the reserved synthetic customer reference")
if sku != f"OPSFLOW-M9E-SKU-{suffix}":
    raise RuntimeError("fixture must use the reserved synthetic SKU")

login = f"opsflow-m9e-{suffix.lower()}@example.invalid"
if env["res.users"].sudo().search_count([("login", "=", login)]):
    raise RuntimeError(
        "sandbox bot already exists; recreate only the disposable database before seeding again"
    )

company = env.company.sudo()
currency = env.ref("base.USD").sudo()
if company.currency_id != currency:
    company.write({"currency_id": currency.id})

warehouse = env["stock.warehouse"].sudo().search([("company_id", "=", company.id)], limit=1)
if not warehouse:
    raise RuntimeError("disposable Odoo database has no default warehouse")

customer_name = f"OpsFlow M9E Synthetic Customer {suffix}"
partner = env["res.partner"].sudo().search([("ref", "=", customer_reference)], limit=1)
if partner:
    if partner.name != customer_name or partner.company_id != company:
        raise RuntimeError("stable synthetic customer reference is already occupied")
else:
    partner = (
        env["res.partner"]
        .sudo()
        .create(
            {
                "name": customer_name,
                "ref": customer_reference,
                "is_company": True,
                "customer_rank": 1,
                "company_id": company.id,
                "active": True,
            }
        )
    )

pricelist_name = f"OpsFlow M9E Synthetic USD {suffix}"
pricelist = (
    env["product.pricelist"]
    .sudo()
    .search([("name", "=", pricelist_name), ("company_id", "=", company.id)], limit=1)
)
if not pricelist:
    pricelist = (
        env["product.pricelist"]
        .sudo()
        .create(
            {
                "name": pricelist_name,
                "currency_id": currency.id,
                "company_id": company.id,
            }
        )
    )

product_name = f"OpsFlow M9E Synthetic Product {suffix}"
product = env["product.product"].sudo().search([("default_code", "=", sku)], limit=1)
if product:
    if product.name != product_name or not product.sale_ok or not product.is_storable:
        raise RuntimeError("stable synthetic SKU is already occupied by another product")
else:
    template = (
        env["product.template"]
        .sudo()
        .create(
            {
                "name": product_name,
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "list_price": 10.0,
                "company_id": company.id,
            }
        )
    )
    product = template.product_variant_id.sudo()
    product.write({"default_code": sku})

quantity = product.with_context(location=warehouse.lot_stock_id.id).qty_available
delta = 100.0 - quantity
if delta:
    env["stock.quant"].sudo()._update_available_quantity(product, warehouse.lot_stock_id, delta)

groups = [
    env.ref("sales_team.group_sale_salesman").id,
    env.ref("stock.group_stock_user").id,
    env.ref("opsflow_sale_bridge.group_opsflow_sale_bridge").id,
]
bot = (
    env["res.users"]
    .sudo()
    .create(
        {
            "name": f"OpsFlow M9E Integration Bot {suffix}",
            "login": login,
            "email": login,
            "company_id": company.id,
            "company_ids": [Command.set([company.id])],
            "group_ids": [Command.set(groups)],
            "active": True,
        }
    )
)

api_key = (
    env["res.users.apikeys"]
    .with_user(bot)
    .sudo()
    ._generate(None, f"OpsFlow M9E disposable {suffix}", None)
)
api_key_path.write_text(api_key)
api_key_path.chmod(0o600)
result = {
    "database": database,
    "customer_reference": customer_reference,
    "sku": sku,
    "company_id": company.id,
    "warehouse_id": warehouse.id,
    "pricelist_id": pricelist.id,
    "partner_id": partner.id,
    "product_id": product.id,
    "bot_user_id": bot.id,
}
result_path.write_text(json.dumps(result))
result_path.chmod(0o600)
env.cr.commit()
print("synthetic Odoo sandbox data prepared; API key stored in a mode-600 local file")
