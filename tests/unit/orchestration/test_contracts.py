from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime
from inspect import signature
from typing import get_type_hints
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.api.orchestration_schemas import OrchestrationIntakeResponse
from opsflow.domain import OrderState, SourceDocumentType
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeCommand,
    OrchestrationIntakeHandler,
    OrchestrationIntakeResult,
)


def _command() -> OrchestrationIntakeCommand:
    return OrchestrationIntakeCommand(
        content=b"original bytes",
        document_type=SourceDocumentType.PDF,
        filename="invoice.pdf",
        mime_type="application/pdf",
        message_id="message-1",
        idempotency_key="event-1",
    )


def test_intake_execution_has_exact_wire_values() -> None:
    assert IntakeExecution.COMPLETED.value == "COMPLETED"
    assert IntakeExecution.STANDING_DOWN.value == "STANDING_DOWN"
    assert [member.value for member in IntakeExecution] == ["COMPLETED", "STANDING_DOWN"]


def test_command_is_immutable_slotted_and_preserves_input_values() -> None:
    command = _command()

    assert is_dataclass(command)
    assert not hasattr(command, "__dict__")
    assert tuple(field.name for field in fields(command)) == (
        "content",
        "document_type",
        "filename",
        "mime_type",
        "message_id",
        "idempotency_key",
        "source_system",
    )
    assert command.content == b"original bytes"
    assert command.filename == "invoice.pdf"
    assert command.message_id == "message-1"
    assert command.idempotency_key == "event-1"
    assert command.source_system is None

    with pytest.raises(FrozenInstanceError):
        command.filename = "changed.pdf"  # type: ignore[misc]


def test_result_is_immutable_slotted_and_preserves_execution_state() -> None:
    result = OrchestrationIntakeResult(
        order_id=UUID(int=1),
        state=OrderState.NEEDS_REVIEW,
        failure_origin=None,
        idempotent_replay=False,
        execution=IntakeExecution.COMPLETED,
    )

    assert is_dataclass(result)
    assert not hasattr(result, "__dict__")
    assert result.execution is IntakeExecution.COMPLETED
    with pytest.raises(FrozenInstanceError):
        result.state = OrderState.FAILED_FINAL  # type: ignore[misc]


def test_handler_protocol_exposes_the_approved_call_signature() -> None:
    parameters = signature(OrchestrationIntakeHandler.__call__).parameters
    annotations = get_type_hints(OrchestrationIntakeHandler.__call__)

    assert tuple(parameters) == ("self", "session", "command", "actor", "recorded_at")
    assert annotations["session"] is AsyncSession
    assert annotations["command"] is OrchestrationIntakeCommand
    assert annotations["actor"] is str
    assert annotations["recorded_at"] is datetime
    assert annotations["return"] is OrchestrationIntakeResult


def test_response_exposes_exactly_four_fields_and_serializes_domain_values() -> None:
    response = OrchestrationIntakeResponse(
        order_id=UUID(int=2),
        state=OrderState.READY_FOR_APPROVAL,
        failure_origin=None,
        idempotent_replay=True,
    )

    assert set(OrchestrationIntakeResponse.model_fields) == {
        "order_id",
        "state",
        "failure_origin",
        "idempotent_replay",
    }
    assert response.model_dump(mode="json") == {
        "order_id": "00000000-0000-0000-0000-000000000002",
        "state": "READY_FOR_APPROVAL",
        "failure_origin": None,
        "idempotent_replay": True,
    }


def test_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OrchestrationIntakeResponse(
            order_id=UUID(int=2),
            state=OrderState.RECEIVED,
            failure_origin=None,
            idempotent_replay=False,
            actor="caller-selected",
        )
