"""Contract checks for the inactive, sanitized Phase 8 Gmail intake workflow."""

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

WORKFLOW_PATH = Path("workflows/n8n/opsflow-gmail-intake.json")
EXPECTED_API_URL = "http://api:8000/v1/orchestration/intakes"
EXPECTED_STATES = {
    "NEEDS_REVIEW",
    "READY_FOR_APPROVAL",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "PROCESSING",
    "EXTRACTED",
}
EXPECTED_NODE_IDS = {
    "Gmail Trigger": "8c000000-0000-4000-8000-000000000001",
    "Prepare Gmail Provenance": "8c000000-0000-4000-8000-000000000002",
    "Normalize Gmail Attachment Envelope": "8c000000-0000-4000-8000-000000000003",
    "Is Attachment Ambiguous": "8c000000-0000-4000-8000-000000000004",
    "AMBIGUOUS_SUPPORTED_ATTACHMENTS": "8c000000-0000-4000-8000-000000000005",
    "Has One Supported Attachment": "8c000000-0000-4000-8000-000000000006",
    "Prepare Attachment Request": "8c000000-0000-4000-8000-000000000007",
    "Has Parser Text": "8c000000-0000-4000-8000-000000000008",
    "Use Parser Text": "8c000000-0000-4000-8000-000000000009",
    "HTML to Visible Text": "8c000000-0000-4000-8000-000000000010",
    "Use HTML Text": "8c000000-0000-4000-8000-000000000011",
    "Normalize Body": "8c000000-0000-4000-8000-000000000012",
    "Has Nonempty Body": "8c000000-0000-4000-8000-000000000013",
    "NO_SUPPORTED_SOURCE": "8c000000-0000-4000-8000-000000000014",
    "Prepare Email Body": "8c000000-0000-4000-8000-000000000015",
    "Create Email Body Document": "8c000000-0000-4000-8000-000000000016",
    "Preserve Original Gmail Intake": "8c000000-0000-4000-8000-000000000017",
    "Submit to OpsFlow API": "8c000000-0000-4000-8000-000000000018",
    "Route Attempt 0 Status": "8c000000-0000-4000-8000-000000000019",
    "Wait Before Retry 1": "8c000000-0000-4000-8000-000000000020",
    "Restore Original After Retry Wait 1": "8c000000-0000-4000-8000-000000000021",
    "Submit to OpsFlow API Retry 1": "8c000000-0000-4000-8000-000000000022",
    "Route Attempt 1 Status": "8c000000-0000-4000-8000-000000000023",
    "Wait Before Retry 2": "8c000000-0000-4000-8000-000000000024",
    "Restore Original After Retry Wait 2": "8c000000-0000-4000-8000-000000000025",
    "Submit to OpsFlow API Retry 2": "8c000000-0000-4000-8000-000000000026",
    "Route Attempt 2 Status": "8c000000-0000-4000-8000-000000000027",
    "Route Backend State": "8c000000-0000-4000-8000-000000000028",
    "Transport Unavailable": "8c000000-0000-4000-8000-000000000029",
    "Review Required": "8c000000-0000-4000-8000-000000000030",
    "Approval Required": "8c000000-0000-4000-8000-000000000031",
    "Retryable Failure": "8c000000-0000-4000-8000-000000000032",
    "Final Failure": "8c000000-0000-4000-8000-000000000033",
    "In Progress": "8c000000-0000-4000-8000-000000000034",
    "Validation Pending": "8c000000-0000-4000-8000-000000000035",
    "Unexpected State": "8c000000-0000-4000-8000-000000000036",
    "Ensure HTML Body Exists": "8c000000-0000-4000-8000-000000000037",
}
FORBIDDEN_CODE_PATTERNS = (
    r"\bfetch\s*\(",
    r"\baxios\b",
    r"\bXMLHttpRequest\b",
    r"\brequire\s*\(",
    r"\bprocess\b",
    r"\$env\b",
    r"\bcredentials?\b",
    r"\bOAuth\b",
    r"\b(?:token|secret|password|apiKey)\b",
    r"\b(?:postgres|mysql|sqlite|redis|database|knex|sequelize|prisma)\b",
    r"\b(?:SELECT\s+.+?\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
    r"\bchild_process\b",
    r"\b(?:fs|filesystem|node:fs|fs/promises|readFile|writeFile|readdir|openSync)\b",
    r"\b(?:Deno|Bun)\b",
    r"\b(?:http|https|net|tls|dgram|socket|WebSocket|EventSource)\b",
    r"\b(?:openai|anthropic|gemini|llm)\b",
    r"\b(?:OrderState|NEEDS_REVIEW|READY_FOR_APPROVAL|FAILED_RETRYABLE|FAILED_FINAL)\b",
    r"\b(?:approval|review|notification|retry|slack|gmail)\b",
    r"\b(?:eval|Function)\s*\(?",
)


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), "the Phase 8 Gmail intake workflow is not present yet"
    exported = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(exported, list) and len(exported) == 1
    workflow = exported[0]
    assert isinstance(workflow, dict)
    return workflow


def _nodes(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in workflow["nodes"]}


def _assignment(node: dict[str, Any], name: str) -> dict[str, Any]:
    assignments = node["parameters"]["assignments"]["assignments"]
    return next(assignment for assignment in assignments if assignment["name"] == name)


def _targets(workflow: dict[str, Any], source: str, output: int = 0) -> list[tuple[str, int]]:
    branches = workflow["connections"][source]["main"][output]
    return [(branch["node"], branch["index"]) for branch in branches]


def _reachable(workflow: dict[str, Any], start: str, goal: str) -> bool:
    queue = deque([start])
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current == goal:
            return True
        if current in visited:
            continue
        visited.add(current)
        for outputs in workflow["connections"].get(current, {}).values():
            for output in outputs:
                queue.extend(target["node"] for target in output)
    return False


def test_workflow_has_frozen_node_inventory_versions_and_wiring() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)

    assert workflow["id"] == "m8cGmailIntake1"
    assert workflow["name"] == "OpsFlow Gmail Intake"
    assert workflow["active"] is False
    assert workflow["tags"] == []
    assert set(nodes) == set(EXPECTED_NODE_IDS)
    assert {name: node["id"] for name, node in nodes.items()} == EXPECTED_NODE_IDS
    assert len({node["id"] for node in workflow["nodes"]}) == len(workflow["nodes"])

    expected_versions = {
        "Gmail Trigger": ("n8n-nodes-base.gmailTrigger", 1.4),
        "Prepare Gmail Provenance": ("n8n-nodes-base.set", 3.5),
        "Normalize Gmail Attachment Envelope": ("n8n-nodes-base.code", 2),
        "Is Attachment Ambiguous": ("n8n-nodes-base.if", 2.3),
        "AMBIGUOUS_SUPPORTED_ATTACHMENTS": ("n8n-nodes-base.stopAndError", 1),
        "Has One Supported Attachment": ("n8n-nodes-base.if", 2.3),
        "Prepare Attachment Request": ("n8n-nodes-base.set", 3.5),
        "Has Parser Text": ("n8n-nodes-base.if", 2.3),
        "Use Parser Text": ("n8n-nodes-base.set", 3.5),
        "HTML to Visible Text": ("n8n-nodes-base.html", 1.2),
        "Use HTML Text": ("n8n-nodes-base.set", 3.5),
        "Normalize Body": ("n8n-nodes-base.set", 3.5),
        "Has Nonempty Body": ("n8n-nodes-base.if", 2.3),
        "NO_SUPPORTED_SOURCE": ("n8n-nodes-base.stopAndError", 1),
        "Prepare Email Body": ("n8n-nodes-base.set", 3.5),
        "Create Email Body Document": ("n8n-nodes-base.moveBinaryData", 1.1),
        "Preserve Original Gmail Intake": ("n8n-nodes-base.set", 3.5),
        "Submit to OpsFlow API": ("n8n-nodes-base.httpRequest", 4.5),
        "Route Attempt 0 Status": ("n8n-nodes-base.if", 2.3),
        "Wait Before Retry 1": ("n8n-nodes-base.wait", 1.1),
        "Restore Original After Retry Wait 1": ("n8n-nodes-base.merge", 3.2),
        "Submit to OpsFlow API Retry 1": ("n8n-nodes-base.httpRequest", 4.5),
        "Route Attempt 1 Status": ("n8n-nodes-base.if", 2.3),
        "Wait Before Retry 2": ("n8n-nodes-base.wait", 1.1),
        "Restore Original After Retry Wait 2": ("n8n-nodes-base.merge", 3.2),
        "Submit to OpsFlow API Retry 2": ("n8n-nodes-base.httpRequest", 4.5),
        "Route Attempt 2 Status": ("n8n-nodes-base.if", 2.3),
        "Route Backend State": ("n8n-nodes-base.switch", 3.4),
        "Transport Unavailable": ("n8n-nodes-base.stopAndError", 1),
        "Review Required": ("n8n-nodes-base.noOp", 1),
        "Approval Required": ("n8n-nodes-base.noOp", 1),
        "Retryable Failure": ("n8n-nodes-base.noOp", 1),
        "Final Failure": ("n8n-nodes-base.noOp", 1),
        "In Progress": ("n8n-nodes-base.noOp", 1),
        "Validation Pending": ("n8n-nodes-base.noOp", 1),
        "Unexpected State": ("n8n-nodes-base.stopAndError", 1),
        "Ensure HTML Body Exists": ("n8n-nodes-base.set", 3.5),
    }
    assert {
        name: (node["type"], node["typeVersion"]) for name, node in nodes.items()
    } == expected_versions

    code_nodes = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.code"]
    assert len(code_nodes) == 1
    code_node = code_nodes[0]
    assert code_node["name"] == "Normalize Gmail Attachment Envelope"
    assert code_node["parameters"]["mode"] == "runOnceForEachItem"
    assert code_node["parameters"]["language"] == "javaScript"
    assert _targets(workflow, "Gmail Trigger") == [("Prepare Gmail Provenance", 0)]
    assert _targets(workflow, "Prepare Gmail Provenance") == [
        ("Normalize Gmail Attachment Envelope", 0)
    ]
    assert _targets(workflow, "Normalize Gmail Attachment Envelope") == [
        ("Is Attachment Ambiguous", 0)
    ]
    ambiguous_rule = nodes["Is Attachment Ambiguous"]["parameters"]["conditions"]["conditions"][0]
    assert ambiguous_rule["leftValue"] == "={{ $json.sourceKind }}"
    assert ambiguous_rule["rightValue"] == "AMBIGUOUS_SUPPORTED_ATTACHMENTS"
    attachment_rule = nodes["Has One Supported Attachment"]["parameters"]["conditions"][
        "conditions"
    ][0]
    assert attachment_rule["leftValue"] == "={{ $json.sourceKind }}"
    assert attachment_rule["rightValue"] == "ATTACHMENT"
    assert _targets(workflow, "Is Attachment Ambiguous") == [("AMBIGUOUS_SUPPORTED_ATTACHMENTS", 0)]
    assert _targets(workflow, "Is Attachment Ambiguous", 1) == [("Has One Supported Attachment", 0)]
    assert _targets(workflow, "Has One Supported Attachment") == [("Prepare Attachment Request", 0)]
    assert _targets(workflow, "Has One Supported Attachment", 1) == [("Has Parser Text", 0)]
    assert not _reachable(workflow, "AMBIGUOUS_SUPPORTED_ATTACHMENTS", "Submit to OpsFlow API")
    assert not _reachable(workflow, "NO_SUPPORTED_SOURCE", "Submit to OpsFlow API")


def test_code_node_is_the_single_bounded_attachment_normalizer() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    code_node = nodes["Normalize Gmail Attachment Envelope"]
    code = code_node["parameters"]["jsCode"]

    assert code_node["type"] == "n8n-nodes-base.code"
    assert code_node["typeVersion"] == 2
    assert len([node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.code"]) == 1
    assert code_node["parameters"]["mode"] == "runOnceForEachItem"
    assert code_node["parameters"]["language"] == "javaScript"
    assert len(code) <= 2_000
    for fragment in (
        "$input.item.binary",
        "Object.keys(binary)",
        "key.startsWith('attachment_')",
        ".toLowerCase().startsWith('image/')",
        r"/\.(pdf|xlsx|csv)$/i",
        "supportedAttachmentCount",
        "supported.length > 1",
        "supported.length === 1",
        "sourceKind",
        "documentType",
        "documentName",
        "documentMimeType",
        "outputBinary.document",
        "if (selected)",
        "mimeType: selected.documentMimeType",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "AMBIGUOUS_SUPPORTED_ATTACHMENTS",
        "BODY_FALLBACK",
    ):
        assert fragment in code
    assert not re.search(r"\bthrow\b", code)
    assert "...selected.file" in code
    assert not re.search(r"\b(?:Buffer|base64|decode|encode|hash|truncate)\b", code)
    assert not any(re.search(pattern, code, re.IGNORECASE) for pattern in FORBIDDEN_CODE_PATTERNS)
    assert _targets(workflow, "Normalize Gmail Attachment Envelope") == [
        ("Is Attachment Ambiguous", 0)
    ]

    for node in workflow["nodes"]:
        node_type = node["type"].lower()
        assert node_type not in {
            "n8n-nodes-base.aitransform",
            "n8n-nodes-base.openai",
            "n8n-nodes-base.googlegemini",
            "n8n-nodes-base.postgres",
            "n8n-nodes-base.mysql",
            "n8n-nodes-base.sqlite",
            "n8n-nodes-base.redis",
            "n8n-nodes-base.slack",
        }
    assert not any(
        node["type"].lower().startswith("n8n-nodes-base.ai") for node in workflow["nodes"]
    )


def test_gmail_trigger_and_provenance_contract() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    trigger = nodes["Gmail Trigger"]
    assert trigger["parameters"]["event"] == "messageReceived"
    assert trigger["parameters"]["simple"] is False
    assert trigger["parameters"]["options"] == {
        "downloadAttachments": True,
        "dataPropertyAttachmentsPrefixName": "attachment_",
    }
    assert trigger["parameters"]["filters"]["q"] == "label:OpsFlow/Intake"
    assert trigger["credentials"]["gmailOAuth2"] == {"name": "OpsFlow Gmail Sandbox"}

    identity = nodes["Prepare Gmail Provenance"]
    assert _assignment(identity, "source_system")["value"] == "GMAIL"
    assert _assignment(identity, "message_id")["value"] == "={{ $json.id }}"
    assert _assignment(identity, "idempotency_key")["value"] == "={{ 'gmail:' + $json.id }}"
    final_identity = nodes["Preserve Original Gmail Intake"]
    assert (
        _assignment(final_identity, "message_id")["value"]
        == "={{ $('Gmail Trigger').item.json.id }}"
    )
    assert _assignment(final_identity, "source_system")["value"] == "GMAIL"
    assert (
        _assignment(final_identity, "idempotency_key")["value"]
        == "={{ 'gmail:' + $('Gmail Trigger').item.json.id }}"
    )


def test_body_fallback_prefers_plain_text_and_creates_email_body_file() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    assert _targets(workflow, "Has Parser Text") == [("Use Parser Text", 0)]
    assert _targets(workflow, "Has Parser Text", 1) == [("Ensure HTML Body Exists", 0)]
    assert _targets(workflow, "Ensure HTML Body Exists") == [("HTML to Visible Text", 0)]
    condition = nodes["Has Parser Text"]["parameters"]["conditions"]["conditions"][0]
    assert condition["leftValue"] == "={{ $json.text !== undefined && $json.text !== null }}"
    assert _targets(workflow, "Use Parser Text") == [("Normalize Body", 0)]
    assert _targets(workflow, "HTML to Visible Text") == [("Use HTML Text", 0)]
    assert nodes["HTML to Visible Text"]["typeVersion"] == 1.2
    assert nodes["HTML to Visible Text"]["parameters"] == {
        "operation": "extractHtmlContent",
        "sourceData": "json",
        "dataPropertyName": "html",
        "extractionValues": {
            "values": [
                {
                    "key": "visibleText",
                    "cssSelector": "body",
                    "returnValue": "text",
                    "returnArray": False,
                }
            ]
        },
        "options": {"trimValues": False, "cleanUpText": False},
    }
    assert (
        _assignment(nodes["Ensure HTML Body Exists"], "html")["value"] == "={{ $json.html ?? '' }}"
    )
    assert _targets(workflow, "Use HTML Text") == [("Normalize Body", 0)]
    normalizer = _assignment(nodes["Normalize Body"], "normalizedBody")["value"]
    assert "replace(/\\r\\n?/g, '\\n')" in normalizer
    assert ".normalize('NFC')" in normalizer
    assert ".trim()" in normalizer
    assert "replace(/\\s+/g" not in normalizer
    assert _targets(workflow, "Has Nonempty Body") == [("Prepare Email Body", 0)]
    assert _targets(workflow, "Has Nonempty Body", 1) == [("NO_SUPPORTED_SOURCE", 0)]
    body_fields = nodes["Prepare Email Body"]["parameters"]["assignments"]["assignments"]
    assert {field["name"]: field["value"] for field in body_fields} == {
        "document_type": "EMAIL_BODY",
        "selectedFileName": "email-body.txt",
        "selectedMimeType": "text/plain",
    }
    assert nodes["Create Email Body Document"]["parameters"] == {
        "mode": "jsonToBinary",
        "convertAllData": False,
        "sourceKey": "normalizedBody",
        "destinationKey": "document",
        "options": {
            "dataIsBase64": False,
            "encoding": "utf8",
            "fileName": "email-body.txt",
            "mimeType": "text/plain",
            "keepSource": True,
        },
    }


def test_multipart_identity_and_binary_property_are_constant_across_attempts() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    attempts = [
        nodes[name]
        for name in (
            "Submit to OpsFlow API",
            "Submit to OpsFlow API Retry 1",
            "Submit to OpsFlow API Retry 2",
        )
    ]
    assert all(attempt["typeVersion"] == 4.5 for attempt in attempts)
    assert all(attempt["parameters"] == attempts[0]["parameters"] for attempt in attempts[1:])
    assert all(attempt["onError"] == "continueErrorOutput" for attempt in attempts)
    assert all(
        attempt["credentials"]["httpBearerAuth"] == {"name": "OpsFlow Orchestration"}
        for attempt in attempts
    )
    assert all(
        "retryOnFail" not in attempt or attempt["retryOnFail"] is False for attempt in attempts
    )

    parameters = attempts[0]["parameters"]
    assert parameters["url"] == EXPECTED_API_URL
    assert parameters["method"] == "POST"
    assert parameters["contentType"] == "multipart-form-data"
    assert parameters["options"]["response"]["response"] == {
        "neverError": True,
        "responseFormat": "json",
        "fullResponse": True,
    }
    fields = parameters["bodyParameters"]["parameters"]
    assert {field["name"] for field in fields} == {
        "document",
        "document_type",
        "message_id",
        "source_system",
    }
    assert next(field for field in fields if field["name"] == "document") == {
        "parameterType": "formBinaryData",
        "name": "document",
        "inputDataFieldName": "document",
    }
    assert (
        next(field for field in fields if field["name"] == "document_type")["value"]
        == "={{ $json.document_type }}"
    )
    assert (
        next(field for field in fields if field["name"] == "message_id")["value"]
        == "={{ $json.message_id }}"
    )
    assert (
        next(field for field in fields if field["name"] == "source_system")["value"]
        == "={{ $json.source_system }}"
    )
    assert parameters["headerParameters"]["parameters"] == [
        {"name": "Idempotency-Key", "value": "={{ $json.idempotency_key }}"}
    ]
    assert nodes["Preserve Original Gmail Intake"]["parameters"]["options"] == {
        "stripBinary": False
    }
    assert _targets(workflow, "Wait Before Retry 1") == [("Restore Original After Retry Wait 1", 1)]
    assert _targets(workflow, "Wait Before Retry 2") == [("Restore Original After Retry Wait 2", 1)]

    for wait in ("Wait Before Retry 1", "Wait Before Retry 2"):
        assert nodes[wait]["parameters"] == {
            "resume": "timeInterval",
            "amount": 1,
            "unit": "seconds",
        }
    assert _targets(workflow, "Route Attempt 0 Status") == [("Wait Before Retry 1", 0)]
    assert _targets(workflow, "Route Attempt 0 Status", 1) == [("Route Backend State", 0)]
    assert _targets(workflow, "Submit to OpsFlow API", 1) == [("Wait Before Retry 1", 0)]
    assert _targets(workflow, "Route Attempt 1 Status") == [("Wait Before Retry 2", 0)]
    assert _targets(workflow, "Route Attempt 1 Status", 1) == [("Route Backend State", 0)]
    assert _targets(workflow, "Submit to OpsFlow API Retry 1", 1) == [("Wait Before Retry 2", 0)]
    assert _targets(workflow, "Route Attempt 2 Status") == [("Transport Unavailable", 0)]
    assert _targets(workflow, "Route Attempt 2 Status", 1) == [("Route Backend State", 0)]
    assert _targets(workflow, "Submit to OpsFlow API Retry 2", 1) == [("Transport Unavailable", 0)]
    for name in ("Route Attempt 0 Status", "Route Attempt 1 Status", "Route Attempt 2 Status"):
        condition = nodes[name]["parameters"]["conditions"]["conditions"][0]
        assert condition["leftValue"] == "={{ $json.statusCode }}"
        assert condition["rightValue"] == 503
        assert condition["operator"] == {"type": "number", "operation": "equals"}


def test_backend_state_routing_is_exact_and_sanitized() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    switch = nodes["Route Backend State"]["parameters"]
    rules = switch["rules"]["values"]
    assert {rule["outputKey"] for rule in rules} == EXPECTED_STATES
    for rule in rules:
        condition = rule["conditions"]["conditions"][0]
        assert condition["leftValue"] == "={{ $json.body.state }}"
        assert condition["rightValue"] == rule["outputKey"]
        assert condition["operator"] == {"type": "string", "operation": "equals"}
    assert switch["options"] == {
        "fallbackOutput": "extra",
        "renameFallbackOutput": "Unexpected State",
    }
    expected_outputs = [
        "Review Required",
        "Approval Required",
        "Retryable Failure",
        "Final Failure",
        "In Progress",
        "Validation Pending",
        "Unexpected State",
    ]
    assert len(workflow["connections"]["Route Backend State"]["main"]) == len(expected_outputs)
    assert [_targets(workflow, "Route Backend State", i) for i in range(len(expected_outputs))] == [
        [(name, 0)] for name in expected_outputs
    ]

    for node in workflow["nodes"]:
        assert node["type"].lower() not in {
            "n8n-nodes-base.aitransform",
            "n8n-nodes-base.openai",
            "n8n-nodes-base.googlegemini",
            "n8n-nodes-base.postgres",
            "n8n-nodes-base.mysql",
            "n8n-nodes-base.sqlite",
            "n8n-nodes-base.redis",
            "n8n-nodes-base.slack",
        }
    serialized = json.dumps(workflow, sort_keys=True).lower()
    assert "localhost" not in serialized and "127.0.0.1" not in serialized
    assert (
        "bearer " not in serialized
        and "access_token" not in serialized
        and "refresh_token" not in serialized
    )
    assert "pinData" not in workflow and "executionData" not in serialized
    assert "customer@example.com" not in serialized and "po-" not in serialized
    credentials = [
        credential
        for node in workflow["nodes"]
        for credential in node.get("credentials", {}).values()
    ]
    assert credentials == [
        {"name": "OpsFlow Gmail Sandbox"},
        {"name": "OpsFlow Orchestration"},
        {"name": "OpsFlow Orchestration"},
        {"name": "OpsFlow Orchestration"},
    ]
    assert all("id" not in credential for credential in credentials)
