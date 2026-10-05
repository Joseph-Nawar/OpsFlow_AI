"""Provider-free contract tests for the scheduled Phase 9 n8n workflow."""

import json
from pathlib import Path
from typing import Any

WORKFLOW_PATH = Path("workflows/n8n/opsflow-order-sync.json")
EXECUTE_NEXT_URL = "http://api:8000/v1/orchestration/order-sync/execute-next"
EXPECTED_OUTCOMES = {
    "completed",
    "worked",
    "yielded",
    "no_work",
    "retry_wait",
    "needs_review",
    "401",
    "503",
    "transport_error",
    "unknown",
}
EXPECTED_BRANCH_NODES = {
    "Completed",
    "Worked",
    "Yielded",
    "No Work",
    "Retry Wait",
    "Needs Review",
    "HTTP 401",
    "HTTP 503",
    "Unknown Outcome",
}
SAFE_OUTPUT_FIELDS = {
    "outcome",
    "http_status",
    "result",
    "order_id",
    "state",
    "failure_code",
}


def _load_workflow() -> dict[str, Any]:
    with WORKFLOW_PATH.open(encoding="utf-8") as workflow_file:
        exported = json.load(workflow_file)
    assert isinstance(exported, dict), "n8n UI import requires one workflow object"
    return exported


def _nodes_by_type(workflow: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in workflow["nodes"] if node.get("type") == node_type]


def _serialized(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _walk_strings(value: object, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [
            pair for key, child in value.items() for pair in _walk_strings(child, f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            pair
            for index, child in enumerate(value)
            for pair in _walk_strings(child, f"{path}[{index}]")
        ]
    if isinstance(value, str):
        return [(path, value)]
    return []


def _graph(workflow: dict[str, Any]) -> dict[str, set[str]]:
    graph = {node["name"]: set() for node in workflow["nodes"]}
    for source, output_sets in workflow["connections"].items():
        for branches in output_sets.values():
            for branch in branches:
                for target in branch:
                    graph[source].add(target["node"])
    return graph


def test_order_sync_workflow_has_one_scheduled_execute_next_request() -> None:
    workflow = _load_workflow()
    schedules = _nodes_by_type(workflow, "n8n-nodes-base.scheduleTrigger")
    requests = _nodes_by_type(workflow, "n8n-nodes-base.httpRequest")
    switches = _nodes_by_type(workflow, "n8n-nodes-base.switch")

    assert workflow["name"] == "OpsFlow Order Sync"
    assert workflow["active"] is False
    assert len(schedules) == 1
    assert len(requests) == 1
    assert len(switches) == 1
    assert schedules[0]["parameters"]["rule"]["interval"] == [
        {"field": "minutes", "minutesInterval": 5}
    ]

    request = requests[0]
    assert request["parameters"]["method"] == "POST"
    assert request["parameters"]["url"] == EXECUTE_NEXT_URL
    assert request["parameters"].get("sendBody", False) is False
    assert request["parameters"].get("bodyParameters") is None
    assert request["parameters"].get("jsonBody") is None
    assert request["parameters"]["authentication"] == "genericCredentialType"
    assert request["parameters"]["genericAuthType"] == "httpBearerAuth"
    assert request["credentials"] == {"httpBearerAuth": {"name": "OpsFlow Orchestration"}}
    assert request["onError"] == "continueErrorOutput"

    graph = _graph(workflow)
    assert graph[schedules[0]["name"]] == {request["name"]}
    assert request["name"] in graph
    assert switches[0]["name"] in graph[request["name"]]

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting, f"workflow has a loop through {node}"
        if node in visited:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def test_http_request_exposes_bounded_response_and_has_no_retry() -> None:
    request = _nodes_by_type(_load_workflow(), "n8n-nodes-base.httpRequest")[0]
    parameters = request["parameters"]
    response = parameters["options"]["response"]["response"]

    assert parameters["options"]["timeout"] == 240000
    assert response["fullResponse"] is True
    assert response["neverError"] is True
    assert response["responseFormat"] == "json"
    assert parameters["options"].get("batching") is None
    assert request["retryOnFail"] is False
    assert "maxTries" not in request
    assert "waitBetweenTries" not in request


def test_workflow_routes_only_bounded_outcomes_and_contains_no_credentials() -> None:
    workflow = _load_workflow()
    serialized = _serialized(workflow)
    switches = _nodes_by_type(workflow, "n8n-nodes-base.switch")
    assert len(switches) == 1

    switch = switches[0]
    rules = switch["parameters"]["rules"]["values"]
    rules_json = _serialized(rules)
    assert {rule["outputKey"] for rule in rules} == EXPECTED_BRANCH_NODES - {"Unknown Outcome"}
    for outcome in EXPECTED_OUTCOMES - {"transport_error", "unknown"}:
        assert outcome in rules_json
    assert "statusCode" in rules_json
    assert "body.result" in rules_json

    set_nodes = _nodes_by_type(workflow, "n8n-nodes-base.set")
    assert set_nodes
    for node in set_nodes:
        assignments = node["parameters"]["assignments"]["assignments"]
        assert {assignment["name"] for assignment in assignments} <= SAFE_OUTPUT_FIELDS
        assert node["parameters"]["includeOtherFields"] is False

    connected_outcomes = {
        target["node"]
        for output in workflow["connections"][switch["name"]]["main"]
        for target in output
    }
    assert connected_outcomes == EXPECTED_BRANCH_NODES
    http_node = _nodes_by_type(workflow, "n8n-nodes-base.httpRequest")[0]
    http_outputs = workflow["connections"][http_node["name"]]["main"]
    transport_targets = {target["node"] for target in http_outputs[1]}
    assert transport_targets == {"Transport Error"}
    assert any("unknown" in node["name"].lower() for node in set_nodes)

    node_types = {node["type"] for node in workflow["nodes"]}
    assert "n8n-nodes-base.wait" not in node_types
    assert "n8n-nodes-base.code" not in node_types
    assert "n8n-nodes-base.function" not in node_types
    assert len(_nodes_by_type(workflow, "n8n-nodes-base.httpRequest")) == 1
    assert "api.hubapi.com" not in serialized
    assert "odoo" not in serialized.lower()
    assert "hubspot" not in serialized.lower()
    assert "Bearer " not in serialized
    assert "pat-" not in serialized
    assert "executionData" not in serialized
    assert workflow["settings"]["saveDataSuccessExecution"] == "none"
    assert workflow["settings"]["saveDataErrorExecution"] == "none"
    assert workflow["settings"]["saveManualExecutions"] is False

    for path, value in _walk_strings(workflow):
        if any(marker in path.lower() for marker in ("password", "apikey", "secret", "token")):
            assert not value.strip(), f"credential-like value at {path}"
