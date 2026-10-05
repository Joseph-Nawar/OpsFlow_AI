# ruff: noqa: B018
{
    "name": "OpsFlow Sale Order Bridge",
    "author": "OpsFlow AI",
    "version": "19.0.1.0.0",
    "summary": "Idempotent OpsFlow sales-order creation",
    "depends": ["sale_stock"],
    "data": ["security/opsflow_sale_bridge_security.xml"],
    "installable": True,
    "license": "LGPL-3",
}
