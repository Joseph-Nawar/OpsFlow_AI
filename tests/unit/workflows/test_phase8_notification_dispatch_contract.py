"""Contract checks for the bounded Phase 8 notification dispatcher."""

import json
from collections import deque
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from opsflow.domain import Order, OrderLine, OrderState, SourceDocument, SourceDocumentType
from opsflow.notifications.contracts import NotificationKind
from opsflow.notifications.payloads import render_slack_payload

WORKFLOW_PATH = Path("workflows/n8n/opsflow-notification-dispatch.json")
CLAIM_URL_EXPRESSION = "={{ 'http://' + 'api' + ':8000' + '/v1/integrations/notifications/claim' }}"
EXPECTED_NODE_TYPES = {
    "Schedule Every Minute": ("n8n-nodes-base.scheduleTrigger", 1.4),
    "Claim One Notification": ("n8n-nodes-base.httpRequest", 4.5),
    "Route Claim Response": ("n8n-nodes-base.switch", 3.4),
    "No Work Available": ("n8n-nodes-base.set", 3.5),
    "Claim Response Failed": ("n8n-nodes-base.set", 3.5),
    "Claim Transport Failed": ("n8n-nodes-base.set", 3.5),
    "Route Notification Channel": ("n8n-nodes-base.switch", 3.4),
    "Unsupported Channel Deferred": ("n8n-nodes-base.set", 3.5),
    "Send Slack Notification": ("n8n-nodes-base.slack", 2.7),
    "Normalize Slack Success": ("n8n-nodes-base.set", 3.5),
    "Normalize Slack Failure": ("n8n-nodes-base.set", 3.5),
    "Reply to Gmail Sender": ("n8n-nodes-base.gmail", 2.2),
    "Normalize Gmail Success": ("n8n-nodes-base.set", 3.5),
    "Normalize Gmail Failure": ("n8n-nodes-base.set", 3.5),
    "Record Notification Outcome": ("n8n-nodes-base.httpRequest", 4.5),
    "Route Outcome Response": ("n8n-nodes-base.switch", 3.4),
    "Outcome Acknowledged": ("n8n-nodes-base.set", 3.5),
    "Outcome Not Confirmed": ("n8n-nodes-base.set", 3.5),
}


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), "the Phase 8 notification dispatcher is not present yet"
    exported = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(exported, list) and len(exported) == 1
    workflow = exported[0]
    assert isinstance(workflow, dict)
    return workflow


def _nodes(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = workflow["nodes"]
    result = {node["name"]: node for node in nodes}
    assert len(result) == len(nodes), "workflow node names must be unique"
    return result


def _targets(workflow: dict[str, Any], source: str, output: int = 0) -> list[str]:
    return [branch["node"] for branch in workflow["connections"][source]["main"][output]]


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
                queue.extend(branch["node"] for branch in output)
    return False


def _is_acyclic(workflow: dict[str, Any]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return False
        if state.get(node) == 2:
            return True
        state[node] = 1
        for outputs in workflow["connections"].get(node, {}).values():
            for output in outputs:
                for branch in output:
                    if not visit(branch["node"]):
                        return False
        state[node] = 2
        return True

    return all(visit(node["name"]) for node in workflow["nodes"])


def _assignment(node: dict[str, Any], name: str) -> dict[str, Any]:
    assignments = node["parameters"]["assignments"]["assignments"]
    return next(assignment for assignment in assignments if assignment["name"] == name)


def _condition_values(node: dict[str, Any]) -> list[tuple[str, Any]]:
    rules = node["parameters"]["rules"]["values"]
    return [
        (
            rule["conditions"]["conditions"][0]["leftValue"],
            rule["conditions"]["conditions"][0]["rightValue"],
        )
        for rule in rules
    ]


def test_export_is_inactive_sanitized_and_uses_local_credential_names() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)

    assert workflow["active"] is False
    assert workflow["settings"]["saveDataSuccessExecution"] == "none"
    assert workflow["settings"]["saveDataErrorExecution"] == "none"
    assert workflow["settings"]["saveManualExecutions"] is False
    assert workflow.get("staticData") is None

    slack = nodes["Send Slack Notification"]
    assert slack["credentials"] == {"slackApi": {"name": "OpsFlow Slack Sandbox"}}
    assert nodes["Claim One Notification"]["credentials"] == {
        "httpBearerAuth": {"name": "OpsFlow Orchestration"}
    }
    assert nodes["Record Notification Outcome"]["credentials"] == {
        "httpBearerAuth": {"name": "OpsFlow Orchestration"}
    }
    assert "id" not in slack["credentials"]["slackApi"]
    assert "id" not in nodes["Claim One Notification"]["credentials"]["httpBearerAuth"]
    assert "id" not in nodes["Record Notification Outcome"]["credentials"]["httpBearerAuth"]
    assert slack["parameters"]["channelId"]["value"] == ""
    serialized = json.dumps(workflow).lower()
    for marker in ("xoxb-", "xoxp-", "client_secret", "access_token", "pindata", "executiondata"):
        assert marker not in serialized


def test_pinned_node_inventory_has_only_the_m8d_and_m8e_transport_nodes() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)

    assert set(nodes) == set(EXPECTED_NODE_TYPES)
    assert len(workflow["nodes"]) == 18
    assert {
        name: (node["type"], node["typeVersion"]) for name, node in nodes.items()
    } == EXPECTED_NODE_TYPES
    assert all(node["id"] for node in nodes.values())
    assert len({node["id"] for node in nodes.values()}) == len(nodes)
    assert all(
        "credentials" not in node
        or all("id" not in credential for credential in node["credentials"].values())
        for node in nodes.values()
    )


def test_schedule_runs_every_minute_and_claims_exactly_once() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    schedule = nodes["Schedule Every Minute"]
    claims = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.httpRequest"
        and node["parameters"].get("url") == CLAIM_URL_EXPRESSION
    ]

    assert schedule["parameters"]["rule"]["interval"] == [
        {"field": "minutes", "minutesInterval": 1}
    ]
    assert _targets(workflow, "Schedule Every Minute") == ["Claim One Notification"]
    assert len(claims) == 1
    assert claims[0]["parameters"]["method"] == "POST"
    assert claims[0]["parameters"]["authentication"] == "genericCredentialType"
    assert claims[0]["parameters"]["genericAuthType"] == "httpBearerAuth"
    assert claims[0]["retryOnFail"] is False
    assert "maxTries" not in claims[0] and "waitBetweenTries" not in claims[0]
    assert claims[0]["parameters"]["options"]["response"]["response"] == {
        "neverError": True,
        "responseFormat": "json",
        "fullResponse": True,
    }


def test_claim_200_routes_once_and_204_stops_before_provider() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    claim_routes = nodes["Route Claim Response"]

    assert _targets(workflow, "Claim One Notification", 0) == ["Route Claim Response"]
    assert _targets(workflow, "Claim One Notification", 1) == ["Claim Transport Failed"]
    assert _condition_values(claim_routes) == [
        ("={{ $json.statusCode }}", 200),
        ("={{ $json.statusCode }}", 204),
    ]
    assert claim_routes["parameters"]["options"]["fallbackOutput"] == "extra"
    assert _targets(workflow, "Route Claim Response", 0) == ["Route Notification Channel"]
    assert _targets(workflow, "Route Claim Response", 1) == ["No Work Available"]
    assert _targets(workflow, "Route Claim Response", 2) == ["Claim Response Failed"]
    assert not _reachable(workflow, "No Work Available", "Send Slack Notification")


def test_channel_switch_sends_only_supported_channel_and_defers_unknown_channels() -> None:
    workflow = _workflow()
    channel = _nodes(workflow)["Route Notification Channel"]

    assert _condition_values(channel) == [
        ("={{ $json.body.channel }}", "SLACK"),
        ("={{ $json.body.channel }}", "GMAIL"),
    ]
    assert channel["parameters"]["options"]["fallbackOutput"] == "extra"
    assert _targets(workflow, "Route Notification Channel", 0) == ["Send Slack Notification"]
    assert _targets(workflow, "Route Notification Channel", 1) == ["Reply to Gmail Sender"]
    assert _targets(workflow, "Route Notification Channel", 2) == ["Unsupported Channel Deferred"]
    assert not _reachable(workflow, "Unsupported Channel Deferred", "Send Slack Notification")
    assert not _reachable(workflow, "Unsupported Channel Deferred", "Reply to Gmail Sender")
    assert (
        _assignment(_nodes(workflow)["Unsupported Channel Deferred"], "operator_outcome")["value"]
        == "UNSUPPORTED_CHANNEL_DEFERRED"
    )


def test_native_slack_27_sends_only_pre_rendered_text_to_local_channel() -> None:
    workflow = _workflow()
    slack = _nodes(workflow)["Send Slack Notification"]
    parameters = slack["parameters"]

    assert parameters["authentication"] == "accessToken"
    assert parameters["resource"] == "message"
    assert parameters["operation"] == "post"
    assert parameters["select"] == "channel"
    assert parameters["channelId"] == {"__rl": True, "value": "", "mode": "id"}
    assert parameters["messageType"] == "text"
    assert parameters["text"] == "={{ $json.body.payload.text }}"
    assert parameters["otherOptions"] == {"includeLinkToWorkflow": False}
    assert slack["retryOnFail"] is False
    assert "maxTries" not in slack and "waitBetweenTries" not in slack
    assert "waitBetweenTries" not in parameters


def test_native_gmail_22_replies_only_to_backend_gmail_claim_payload() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    gmail = nodes["Reply to Gmail Sender"]
    parameters = gmail["parameters"]

    assert gmail["credentials"] == {"gmailOAuth2": {"name": "OpsFlow Gmail Sandbox"}}
    assert gmail["retryOnFail"] is False
    assert gmail["onError"] == "continueErrorOutput"
    assert "maxTries" not in gmail and "waitBetweenTries" not in gmail
    assert parameters["authentication"] == "oAuth2"
    assert parameters["resource"] == "message"
    assert parameters["operation"] == "reply"
    assert parameters["messageId"] == "={{ $json.body.payload.message_id }}"
    assert parameters["emailType"] == "text"
    assert parameters["message"] == "={{ $json.body.payload.body }}"
    assert parameters["options"] == {
        "appendAttribution": False,
        "replyToSenderOnly": True,
    }
    assert parameters["message"] != "Your purchase order has been approved for processing."
    assert all(key not in parameters for key in ("to", "sendTo", "attachmentsUi", "threadId"))
    assert _targets(workflow, "Route Notification Channel", 1) == ["Reply to Gmail Sender"]
    assert _targets(workflow, "Reply to Gmail Sender", 0) == ["Normalize Gmail Success"]
    assert _targets(workflow, "Reply to Gmail Sender", 1) == ["Normalize Gmail Failure"]


def test_gmail_success_keeps_only_confirmed_reply_id_and_claim_identity() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    success = nodes["Normalize Gmail Success"]

    assignments = success["parameters"]["assignments"]["assignments"]
    assert {assignment["name"] for assignment in assignments} == {
        "notification_id",
        "claim_token",
        "outcome",
        "provider_reference",
    }
    assert _assignment(success, "notification_id")["value"] == (
        "={{ $('Claim One Notification').item.json.body.notification_id }}"
    )
    assert _assignment(success, "claim_token")["value"] == (
        "={{ $('Claim One Notification').item.json.body.claim_token }}"
    )
    assert _assignment(success, "outcome")["value"] == "DELIVERED"
    assert _assignment(success, "provider_reference")["value"] == "={{ $json.id }}"
    assert success["parameters"]["includeOtherFields"] is False
    assert _targets(workflow, "Normalize Gmail Success") == ["Record Notification Outcome"]


def test_gmail_failure_is_allowlisted_and_drops_provider_diagnostics() -> None:
    workflow = _workflow()
    failure = _nodes(workflow)["Normalize Gmail Failure"]
    assignments = failure["parameters"]["assignments"]["assignments"]

    assert {assignment["name"] for assignment in assignments} == {
        "notification_id",
        "claim_token",
        "outcome",
        "failure_code",
    }
    assert _assignment(failure, "notification_id")["value"] == (
        "={{ $('Claim One Notification').item.json.body.notification_id }}"
    )
    assert _assignment(failure, "claim_token")["value"] == (
        "={{ $('Claim One Notification').item.json.body.claim_token }}"
    )
    assert _assignment(failure, "outcome")["value"] == "FAILED"
    assert _assignment(failure, "failure_code")["value"] == "UNKNOWN_FAILURE"
    assert failure["parameters"]["includeOtherFields"] is False
    assert "retry_after_seconds" not in {assignment["name"] for assignment in assignments}
    assert _targets(workflow, "Normalize Gmail Failure") == ["Record Notification Outcome"]


def test_slack_text_is_passed_unchanged_and_backend_contract_caps_it_at_4000() -> None:
    slack = _nodes(_workflow())["Send Slack Notification"]["parameters"]
    assert slack["text"] == "={{ $json.body.payload.text }}"

    order_id = UUID("12345678-1234-5678-9abc-def012345678")
    order = Order(
        id=order_id,
        customer_reference="synthetic-customer",
        po_number="synthetic-po",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 1, 2),
        currency="USD",
        lines=(
            OrderLine(
                id=UUID(int=2),
                sku="synthetic-sku",
                description="synthetic line",
                quantity=Decimal("1"),
                submitted_price=Decimal("1"),
                trusted_catalogue_price=Decimal("1"),
            ),
        ),
        source_documents=(
            SourceDocument(
                id=UUID(int=3),
                document_type=SourceDocumentType.EMAIL_BODY,
                name="synthetic.txt",
                mime_type="text/plain",
                sha256="a" * 64,
                message_id=None,
                storage_reference=None,
                metadata=(),
            ),
        ),
        state=OrderState.NEEDS_REVIEW,
    )
    payload = render_slack_payload(
        NotificationKind.REVIEW_REQUIRED,
        order,
        (),
        "https://example.test/" + "x" * 5_000,
    )
    assert isinstance(payload["text"], str)
    assert len(payload["text"]) == 4_000


def test_success_records_only_confirmed_slack_timestamp_and_exact_claim_identity() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    success = nodes["Normalize Slack Success"]

    assignments = success["parameters"]["assignments"]["assignments"]
    assert {assignment["name"] for assignment in assignments} == {
        "notification_id",
        "claim_token",
        "outcome",
        "provider_reference",
    }
    assert _assignment(success, "notification_id")["value"] == (
        "={{ $('Claim One Notification').item.json.body.notification_id }}"
    )
    assert _assignment(success, "claim_token")["value"] == (
        "={{ $('Claim One Notification').item.json.body.claim_token }}"
    )
    assert _assignment(success, "outcome")["value"] == "DELIVERED"
    assert _assignment(success, "provider_reference")["value"] == "={{ $json.message_timestamp }}"
    assert success["parameters"]["includeOtherFields"] is False
    assert _targets(workflow, "Send Slack Notification", 0) == ["Normalize Slack Success"]


def test_failure_is_allowlisted_and_omits_unexposed_retry_after_and_provider_text() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    failure = nodes["Normalize Slack Failure"]
    assignments = failure["parameters"]["assignments"]["assignments"]

    assert {assignment["name"] for assignment in assignments} == {
        "notification_id",
        "claim_token",
        "outcome",
        "failure_code",
    }
    assert _assignment(failure, "notification_id")["value"] == (
        "={{ $('Claim One Notification').item.json.body.notification_id }}"
    )
    assert _assignment(failure, "claim_token")["value"] == (
        "={{ $('Claim One Notification').item.json.body.claim_token }}"
    )
    assert _assignment(failure, "outcome")["value"] == "FAILED"
    assert _assignment(failure, "failure_code")["value"] == "UNKNOWN_FAILURE"
    assert failure["parameters"]["includeOtherFields"] is False
    assert "retry_after_seconds" not in {assignment["name"] for assignment in assignments}
    assert _targets(workflow, "Send Slack Notification", 1) == ["Normalize Slack Failure"]


def test_one_authenticated_outcome_request_handles_each_provider_result_once() -> None:
    workflow = _workflow()
    nodes = _nodes(workflow)
    outcomes = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.httpRequest"
        and "/v1/integrations/notifications/" in node["parameters"].get("url", "")
        and "/outcome" in node["parameters"].get("url", "")
    ]
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["parameters"]["method"] == "POST"
    assert outcome["parameters"]["authentication"] == "genericCredentialType"
    assert outcome["parameters"]["genericAuthType"] == "httpBearerAuth"
    expected_outcome_url = (
        "={{ 'http://' + 'api' + ':8000' + '/v1/integrations/notifications/'"
        " + $json.notification_id + '/outcome' }}"
    )
    assert outcome["parameters"]["url"] == expected_outcome_url
    body = outcome["parameters"]["jsonBody"]
    assert "claim_token: $json.claim_token" in body
    assert "outcome: 'DELIVERED'" in body and "provider_reference: $json.provider_reference" in body
    assert "outcome: 'FAILED'" in body and "failure_code: $json.failure_code" in body
    assert "error" not in body.lower() and "headers" not in body.lower()
    assert _targets(workflow, "Normalize Slack Success") == ["Record Notification Outcome"]
    assert _targets(workflow, "Normalize Slack Failure") == ["Record Notification Outcome"]
    assert _targets(workflow, "Normalize Gmail Success") == ["Record Notification Outcome"]
    assert _targets(workflow, "Normalize Gmail Failure") == ["Record Notification Outcome"]
    assert _targets(workflow, "Record Notification Outcome", 0) == ["Route Outcome Response"]
    assert _targets(workflow, "Record Notification Outcome", 1) == ["Outcome Not Confirmed"]
    assert _condition_values(nodes["Route Outcome Response"]) == [
        ("={{ $json.statusCode }}", 200),
    ]
    assert _targets(workflow, "Route Outcome Response", 0) == ["Outcome Acknowledged"]
    assert _targets(workflow, "Route Outcome Response", 1) == ["Outcome Not Confirmed"]


def test_graph_has_no_provider_retries_loops_or_out_of_scope_nodes() -> None:
    workflow = _workflow()
    allowed = {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.switch",
        "n8n-nodes-base.set",
        "n8n-nodes-base.slack",
        "n8n-nodes-base.gmail",
    }
    assert {node["type"] for node in workflow["nodes"]} <= allowed
    assert sum(node["type"] == "n8n-nodes-base.slack" for node in workflow["nodes"]) == 1
    assert sum(node["type"] == "n8n-nodes-base.gmail" for node in workflow["nodes"]) == 1
    assert sum(node["type"] == "n8n-nodes-base.httpRequest" for node in workflow["nodes"]) == 2
    assert all(node.get("retryOnFail", False) is False for node in workflow["nodes"])
    assert all(
        "maxTries" not in node and "waitBetweenTries" not in node for node in workflow["nodes"]
    )
    assert not any("wait" in node["type"].lower() for node in workflow["nodes"])
    assert _is_acyclic(workflow)
    assert _reachable(workflow, "Schedule Every Minute", "Send Slack Notification")
    assert _reachable(workflow, "Schedule Every Minute", "Reply to Gmail Sender")
    assert _targets(workflow, "Send Slack Notification", 0) == ["Normalize Slack Success"]
    assert _targets(workflow, "Send Slack Notification", 1) == ["Normalize Slack Failure"]
    assert not _reachable(workflow, "Send Slack Notification", "Reply to Gmail Sender")
    assert not _reachable(workflow, "Reply to Gmail Sender", "Send Slack Notification")
    assert not any(
        node["type"].lower().endswith(("postgres", "mysql", "code", "openai", "wait"))
        for node in workflow["nodes"]
    )
