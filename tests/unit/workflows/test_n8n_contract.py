"""Contract tests for the committed Phase 7 n8n sandbox workflow."""

import json
from pathlib import Path
from typing import Any

WORKFLOW_PATH = Path("workflows/n8n/opsflow-sandbox-intake.json")
EXPECTED_API_URL = "http://api:8000/v1/orchestration/intakes"
EXPECTED_STATES = {
    "NEEDS_REVIEW",
    "READY_FOR_APPROVAL",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "PROCESSING",
    "EXTRACTED",
}
FORBIDDEN_NODE_MARKERS = {
    "code",
    "function",
    "postgres",
    "mysql",
    "sqlite",
    "redis",
    "gmail",
    "slack",
    "salesforce",
    "hubspot",
    "odoo",
    "sap",
    "gemini",
    "openai",
    "langchain",
}


def _load_workflow() -> dict[str, Any]:
    with WORKFLOW_PATH.open(encoding="utf-8") as workflow_file:
        exported = json.load(workflow_file)
    assert isinstance(exported, list)
    assert len(exported) == 1
    workflow = exported[0]
    assert isinstance(workflow, dict)
    return workflow


def _nodes_by_type(workflow: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in workflow["nodes"] if node.get("type") == node_type]


def _serialized(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _walk_strings(value: object, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        strings: list[tuple[str, str]] = []
        for key, child in value.items():
            strings.extend(_walk_strings(child, f"{path}.{key}"))
        return strings
    if isinstance(value, list):
        strings = []
        for index, child in enumerate(value):
            strings.extend(_walk_strings(child, f"{path}[{index}]"))
        return strings
    if isinstance(value, str):
        return [(path, value)]
    return []


def test_sandbox_workflow_has_the_approved_topology() -> None:
    workflow = _load_workflow()

    assert workflow["name"] == "OpsFlow Sandbox Intake"
    assert isinstance(workflow["nodes"], list)
    assert _nodes_by_type(workflow, "n8n-nodes-base.webhook")
    assert _nodes_by_type(workflow, "n8n-nodes-base.httpRequest")
    assert _nodes_by_type(workflow, "n8n-nodes-base.switch")
    assert _nodes_by_type(workflow, "n8n-nodes-base.respondToWebhook")


def test_webhook_and_http_request_contract_is_exact() -> None:
    workflow = _load_workflow()
    webhooks = _nodes_by_type(workflow, "n8n-nodes-base.webhook")
    http_requests = _nodes_by_type(workflow, "n8n-nodes-base.httpRequest")

    assert len(webhooks) == 1
    webhook = webhooks[0]
    assert webhook["parameters"]["httpMethod"] == "POST"
    assert webhook["parameters"]["path"] == "opsflow-sandbox-intake"
    assert webhook["parameters"]["responseMode"] == "responseNode"

    assert len(http_requests) == 1
    http_request = http_requests[0]
    parameters = http_request["parameters"]
    assert parameters["method"] == "POST"
    assert parameters["url"] == EXPECTED_API_URL
    assert parameters["contentType"] == "multipart-form-data"

    body_fields = parameters["bodyParameters"]["parameters"]
    assert {field["name"] for field in body_fields} == {
        "document",
        "document_type",
        "message_id",
    }
    binary_field = next(field for field in body_fields if field["name"] == "document")
    assert binary_field["parameterType"] == "formBinaryData"
    assert binary_field["inputDataFieldName"] == "document"
    document_type_field = next(field for field in body_fields if field["name"] == "document_type")
    assert document_type_field["parameterType"] == "formData"
    assert "$json.body.document_type" in document_type_field["value"]
    message_id_field = next(field for field in body_fields if field["name"] == "message_id")
    assert message_id_field["parameterType"] == "formData"
    assert "$json.body.message_id" in message_id_field["value"]

    headers = parameters["headerParameters"]["parameters"]
    idempotency_header = next(header for header in headers if header["name"] == "Idempotency-Key")
    assert "$json.headers" in idempotency_header["value"]
    assert "x-opsflow-event-id" in idempotency_header["value"].lower()

    assert parameters["authentication"] == "genericCredentialType"
    assert parameters["genericAuthType"] == "httpBearerAuth"
    credential = http_request["credentials"]["httpBearerAuth"]
    assert credential == {"name": "OpsFlow Orchestration"}


def test_switch_routes_only_on_server_state_with_safe_default() -> None:
    workflow = _load_workflow()
    switches = _nodes_by_type(workflow, "n8n-nodes-base.switch")
    assert len(switches) == 1
    switch = switches[0]
    switch_parameters = switch["parameters"]
    rules = switch_parameters["rules"]["values"]
    assert {rule["outputKey"] for rule in rules} == EXPECTED_STATES
    for rule in rules:
        condition = rule["conditions"]["conditions"][0]
        assert condition["leftValue"] == "={{ $json.state }}"
        assert condition["rightValue"] == rule["outputKey"]
        assert condition["operator"] == {"type": "string", "operation": "equals"}
    assert switch_parameters["options"] == {
        "fallbackOutput": "extra",
        "renameFallbackOutput": "Unexpected State",
    }
    assert "Unexpected State" in _serialized(workflow["nodes"])
    assert len(workflow["connections"][switch["name"]]["main"]) == len(EXPECTED_STATES) + 1

    response_nodes = _nodes_by_type(workflow, "n8n-nodes-base.respondToWebhook")
    assert {node["name"] for node in response_nodes} == EXPECTED_STATES | {"Unexpected State"}


def test_workflow_has_no_business_authority_or_embedded_private_data() -> None:
    workflow = _load_workflow()
    for node in workflow["nodes"]:
        lowered_type = node["type"].lower()
        assert not any(marker in lowered_type for marker in FORBIDDEN_NODE_MARKERS)
        assert "retryOnFail" not in node.get("parameters", {})
        assert "waitBetweenTries" not in node.get("parameters", {})

    serialized = _serialized(workflow)
    assert EXPECTED_API_URL in serialized
    assert "localhost" not in serialized
    assert "127.0.0.1" not in serialized
    assert "pinData" not in workflow
    assert "executionData" not in serialized
    assert "Bearer " not in serialized
    assert "CUST-001" not in serialized
    assert "PO-SYNTHETIC" not in serialized

    for path, value in _walk_strings(workflow):
        lowered_path = path.lower()
        if any(
            marker in lowered_path
            for marker in ("authorization", "apikey", "password", "secret", "encryption")
        ):
            assert not value.strip(), f"usable secret-like value at {path}"
