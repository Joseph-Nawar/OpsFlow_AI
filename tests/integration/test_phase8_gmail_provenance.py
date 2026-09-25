"""PostgreSQL and HTTP proofs for Phase 8 Gmail source provenance."""

import asyncio
from datetime import date

import httpx
import pytest
from test_phase7_pipeline import (
    _assert_gmail_changed_bytes_conflict,
    _assert_gmail_provenance_replay,
    _assert_invalid_gmail_provenance_has_no_database_effect,
    _build_test_app,
    _post_intake,
    _table_counts,
)


def test_gmail_provenance_persists_and_same_source_replays_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_gmail_provenance_replay(monkeypatch))


def test_gmail_changed_bytes_conflict_without_second_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_gmail_changed_bytes_conflict(monkeypatch))


@pytest.mark.parametrize(
    ("source_system", "message_id", "key"),
    [
        ("GMAIL", None, "gmail:missing-message-id"),
        ("GMAIL", "   ", "gmail:   "),
        ("GMAIL", "phase8-wrong-key", "wrong-key"),
        ("OUTLOOK", "phase8-unsupported-source", "outlook:phase8-unsupported-source"),
    ],
)
def test_invalid_gmail_provenance_has_no_database_effect(
    monkeypatch: pytest.MonkeyPatch,
    source_system: str,
    message_id: str | None,
    key: str,
) -> None:
    asyncio.run(
        _assert_invalid_gmail_provenance_has_no_database_effect(
            monkeypatch, source_system, message_id, key
        )
    )


def test_gmail_prefixed_key_over_128_characters_returns_422_before_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_gmail_prefixed_key_too_long_has_no_database_effect(monkeypatch))


async def _assert_gmail_prefixed_key_too_long_has_no_database_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_id = "m" * 123
    key = f"gmail:{message_id}"
    before = await _table_counts()
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await _post_intake(
            client,
            key,
            message_id=message_id,
            source_system="GMAIL",
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert message_id not in response.text
    assert await _table_counts() == before
