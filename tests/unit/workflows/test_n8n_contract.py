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

    assert len(http_requests) == 3
    for http_request in http_requests:
        assert http_request["typeVersion"] == 4.5
        parameters = http_request["parameters"]
        assert parameters["method"] == "POST"
        assert parameters["url"] == EXPECTED_API_URL
        assert parameters["contentType"] == "multipart-form-data"
        assert parameters["authentication"] == "genericCredentialType"
        assert parameters["genericAuthType"] == "httpBearerAuth"
        assert http_request["credentials"]["httpBearerAuth"] == {"name": "OpsFlow Orchestration"}

        response = parameters["options"]["response"]["response"]
        assert response["neverError"] is True
        assert response["responseFormat"] == "json"
        assert response["fullResponse"] is True
        assert http_request["onError"] == "continueErrorOutput"
        assert "retryOnFail" not in parameters
        assert "maxTries" not in parameters
        assert "waitBetweenTries" not in parameters

        body_fields = parameters["bodyParameters"]["parameters"]
        assert {field["name"] for field in body_fields} == {
            "document",
            "document_type",
            "message_id",
        }
        binary_field = next(field for field in body_fields if field["name"] == "document")
        assert binary_field["parameterType"] == "formBinaryData"
        assert binary_field["inputDataFieldName"] == "document"
        document_type_field = next(
            field for field in body_fields if field["name"] == "document_type"
        )
        assert document_type_field["parameterType"] == "formData"
        assert "$('Webhook').item.json.body.document_type" in document_type_field["value"]
        message_id_field = next(field for field in body_fields if field["name"] == "message_id")
        assert message_id_field["parameterType"] == "formData"
        assert "$('Webhook').item.json.body.message_id" in message_id_field["value"]

        headers = parameters["headerParameters"]["parameters"]
        idempotency_header = next(
            header for header in headers if header["name"] == "Idempotency-Key"
        )
        assert "$('Webhook').item.json.headers" in idempotency_header["value"]
        assert "x-opsflow-event-id" in idempotency_header["value"].lower()


def test_switch_routes_only_on_server_state_with_safe_default() -> None:
    workflow = _load_workflow()
    switches = _nodes_by_type(workflow, "n8n-nodes-base.switch")
    assert len(switches) == 4
    status_switches = [switch for switch in switches if "Status" in switch["name"]]
    assert len(status_switches) == 3
    for switch in status_switches:
        rules = switch["parameters"]["rules"]["values"]
        assert len(rules) == 1
        condition = rules[0]["conditions"]["conditions"][0]
        assert condition["leftValue"] == "={{ $json.statusCode }}"
        assert condition["rightValue"] == 503
        assert condition["operator"] == {"type": "number", "operation": "equals"}
        assert "500" not in _serialized(switch).lower()
        assert "5xx" not in _serialized(switch).lower()

    switch = next(switch for switch in switches if switch["name"] == "Route Backend State")
    switch_parameters = switch["parameters"]
    rules = switch_parameters["rules"]["values"]
    assert {rule["outputKey"] for rule in rules} == EXPECTED_STATES
    for rule in rules:
        condition = rule["conditions"]["conditions"][0]
        assert condition["leftValue"] == "={{ $json.body.state }}"
        assert condition["rightValue"] == rule["outputKey"]
        assert condition["operator"] == {"type": "string", "operation": "equals"}
    assert switch_parameters["options"] == {
        "fallbackOutput": "extra",
        "renameFallbackOutput": "Unexpected State",
    }
    assert "Unexpected State" in _serialized(workflow["nodes"])
    assert len(workflow["connections"][switch["name"]]["main"]) == len(EXPECTED_STATES) + 1

    response_nodes = _nodes_by_type(workflow, "n8n-nodes-base.respondToWebhook")
    assert {node["name"] for node in response_nodes} == EXPECTED_STATES | {
        "Unexpected State",
        "Transport Unavailable",
    }


def test_workflow_has_no_business_authority_or_embedded_private_data() -> None:
    workflow = _load_workflow()
    for node in workflow["nodes"]:
        lowered_type = node["type"].lower()
        assert not any(marker in lowered_type for marker in FORBIDDEN_NODE_MARKERS)
        assert "retryOnFail" not in node.get("parameters", {})
        assert "waitBetweenTries" not in node.get("parameters", {})
        assert node["type"] != "n8n-nodes-base.code"
        assert node["type"] != "n8n-nodes-base.function"

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


def test_workflow_has_a_finite_two_retry_transport_dag() -> None:
    workflow = _load_workflow()
    waits = _nodes_by_type(workflow, "n8n-nodes-base.wait")
    assert len(waits) == 2
    assert all("retry" in node["name"].lower() for node in waits)

    restorers = [
        node
        for node in workflow["nodes"]
        if node["name"]
        in {
            "Restore Original After Retry Wait 1",
            "Restore Original After Retry Wait 2",
        }
    ]
    assert len(restorers) == 2
    for restorer in restorers:
        assert restorer["type"] == "n8n-nodes-base.merge"
        assert restorer["typeVersion"] == 3.2
        assert restorer["parameters"] == {
            "mode": "combine",
            "combineBy": "combineByPosition",
            "options": {"includeUnpaired": False},
        }

    names = {node["name"] for node in workflow["nodes"]}
    assert {
        "Submit to OpsFlow API",
        "Submit to OpsFlow API Retry 1",
        "Submit to OpsFlow API Retry 2",
        "Transport Unavailable",
    } <= names

    http_names = {node["name"] for node in _nodes_by_type(workflow, "n8n-nodes-base.httpRequest")}
    assert len(http_names) == 3
    for name in http_names:
        connections = workflow["connections"][name]
        assert len(connections["main"]) == 2
        assert connections["main"][1]

    unavailable = next(
        node for node in workflow["nodes"] if node["name"] == "Transport Unavailable"
    )
    assert unavailable["parameters"]["options"]["responseCode"] == 503
    assert '"state": "UNAVAILABLE"' in unavailable["parameters"]["responseBody"]

    graph: dict[str, set[str]] = {name: set() for name in names}
    for source, outputs in workflow["connections"].items():
        for branches in outputs.values():
            for branch in branches:
                for target in branch:
                    graph[source].add(target["node"])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise AssertionError("workflow retry graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for child in graph[node]:
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def test_retry_transport_outputs_have_no_silent_terminal_branch() -> None:
    workflow = _load_workflow()
    connections = workflow["connections"]

    def targets(source: str, output_index: int) -> list[dict[str, Any]]:
        return connections[source]["main"][output_index]

    def assert_target(
        source: str,
        output_index: int,
        target: str,
        target_input: int | None = None,
    ) -> None:
        matching = [item for item in targets(source, output_index) if item["node"] == target]
        assert matching, f"{source} output {output_index} does not reach {target}"
        if target_input is not None:
            assert any(item["index"] == target_input for item in matching)

    assert_target("Submit to OpsFlow API", 0, "Route Attempt 0 Status")
    assert_target("Submit to OpsFlow API", 1, "Wait Before Retry 1")
    assert_target("Route Attempt 0 Status", 0, "Wait Before Retry 1")
    assert_target("Route Attempt 0 Status", 1, "Route Backend State")
    assert_target("Wait Before Retry 1", 0, "Restore Original After Retry Wait 1", 1)
    assert_target("Restore Original After Retry Wait 1", 0, "Submit to OpsFlow API Retry 1")

    assert_target("Submit to OpsFlow API Retry 1", 0, "Route Attempt 1 Status")
    assert_target("Submit to OpsFlow API Retry 1", 1, "Wait Before Retry 2")
    assert_target("Route Attempt 1 Status", 0, "Wait Before Retry 2")
    assert_target("Route Attempt 1 Status", 1, "Route Backend State")
    assert_target("Wait Before Retry 2", 0, "Restore Original After Retry Wait 2", 1)
    assert_target("Restore Original After Retry Wait 2", 0, "Submit to OpsFlow API Retry 2")

    assert_target("Submit to OpsFlow API Retry 2", 0, "Route Attempt 2 Status")
    assert_target("Submit to OpsFlow API Retry 2", 1, "Transport Unavailable")
    assert_target("Route Attempt 2 Status", 0, "Transport Unavailable")
    assert_target("Route Attempt 2 Status", 1, "Route Backend State")

    for status_router in (
        "Route Attempt 0 Status",
        "Route Attempt 1 Status",
        "Route Attempt 2 Status",
    ):
        for branch in targets(status_router, 1):
            assert branch["node"] == "Route Backend State"

    for output in connections["Route Backend State"]["main"]:
        assert output
        assert output[0]["node"] in EXPECTED_STATES | {"Unexpected State"}
