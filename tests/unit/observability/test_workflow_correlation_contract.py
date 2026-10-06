"""n8n correlation headers remain diagnostic and stable across transport retries."""

import json
from pathlib import Path
from typing import Any

import pytest

WORKFLOW_PATHS = (
    Path("workflows/n8n/opsflow-sandbox-intake.json"),
    Path("workflows/n8n/opsflow-gmail-intake.json"),
    Path("workflows/n8n/opsflow-notification-dispatch.json"),
    Path("workflows/n8n/opsflow-order-sync.json"),
)
EXECUTION_ID = "={{ $execution.id }}"


def _walk_http_nodes(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("type") == "n8n-nodes-base.httpRequest"
    ]


@pytest.mark.parametrize("path", WORKFLOW_PATHS)
def test_every_opsflow_http_request_carries_the_same_n8n_execution_correlation(
    path: Path,
) -> None:
    exported = json.loads(path.read_text(encoding="utf-8"))
    workflow = exported[0] if isinstance(exported, list) else exported
    requests = _walk_http_nodes(workflow)
    assert requests
    for node in requests:
        parameters = node["parameters"]
        headers = parameters.get("headerParameters", {}).get("parameters", [])
        values = [
            header["value"] for header in headers if header.get("name") == "X-Workflow-Execution-ID"
        ]
        assert values == [EXECUTION_ID], node["name"]
        assert "retryOnFail" not in parameters
        assert "maxTries" not in parameters
        assert "waitBetweenTries" not in parameters
