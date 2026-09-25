"""Deterministic retry policy for durable notification outcomes."""

import pytest

from opsflow.notifications.service import _retry_delay_seconds


@pytest.mark.parametrize(
    ("attempt", "slack", "hint", "expected"),
    [
        (1, False, None, 30),
        (2, False, 300, 120),
        (1, True, None, 30),
        (1, True, 0, 30),
        (1, True, 60, 60),
        (2, True, 30, 120),
        (2, True, 121, 121),
        (2, True, 300, 300),
    ],
)
def test_retry_delay_uses_backend_schedule_and_bounded_slack_hint(
    attempt: int,
    slack: bool,
    hint: int | None,
    expected: int,
) -> None:
    assert _retry_delay_seconds(attempt, slack=slack, retry_after_seconds=hint) == expected


@pytest.mark.parametrize("hint", [-1, 301, True])
def test_service_rejects_invalid_retry_hints_even_beyond_api_validation(hint: object) -> None:
    with pytest.raises(ValueError):
        _retry_delay_seconds(1, slack=True, retry_after_seconds=hint)  # type: ignore[arg-type]
