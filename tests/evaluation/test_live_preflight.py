from __future__ import annotations

import pytest

from opsflow.evaluation.commands import (
    LivePreflightError,
    run_evaluation,
    validate_live_preflight,
)
from opsflow.evaluation.models import EvaluationMode

VALID_ENV = {
    "OPSFLOW_EVALUATION_LIVE_GEMINI": "1",
    "OPSFLOW_GEMINI_API_KEY": "test-key-not-used",
    "OPSFLOW_GEMINI_MODEL": "gemini-3.8-flash",
    "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "30",
}


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {**VALID_ENV, "OPSFLOW_EVALUATION_LIVE_GEMINI": ""},
        {**VALID_ENV, "OPSFLOW_EVALUATION_LIVE_GEMINI": "true"},
        {key: value for key, value in VALID_ENV.items() if key != "OPSFLOW_GEMINI_API_KEY"},
        {**VALID_ENV, "OPSFLOW_GEMINI_API_KEY": "   "},
        {key: value for key, value in VALID_ENV.items() if key != "OPSFLOW_GEMINI_MODEL"},
        {**VALID_ENV, "OPSFLOW_GEMINI_MODEL": "   "},
        {key: value for key, value in VALID_ENV.items() if key != "OPSFLOW_GEMINI_TIMEOUT_SECONDS"},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": ""},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "not-a-number"},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "nan"},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "inf"},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "0"},
        {**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "-1"},
    ],
)
def test_live_preflight_rejects_missing_or_invalid_runtime_configuration(
    environment: dict[str, str],
) -> None:
    with pytest.raises(LivePreflightError):
        validate_live_preflight(environment)


def test_live_preflight_uses_existing_gemini_config_and_does_not_require_pricing() -> None:
    config = validate_live_preflight(VALID_ENV)

    assert config.model == "gemini-3.8-flash"
    assert config.timeout_seconds == 30
    assert config.api_key == "test-key-not-used"


def test_live_preflight_rejects_overflow_timeout() -> None:
    with pytest.raises(LivePreflightError):
        validate_live_preflight({**VALID_ENV, "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "1e309"})


def test_invalid_live_preflight_stops_before_corpus_or_database_work(monkeypatch) -> None:
    import opsflow.evaluation.commands as commands

    class SettingsStub:
        database_url = "postgresql+asyncpg://opsflow:opsflow@localhost/opsflow"

    monkeypatch.setattr(commands, "Settings", lambda **_kwargs: SettingsStub())
    monkeypatch.setattr(
        commands,
        "load_manifest",
        lambda *_args: pytest.fail("corpus must not load before live preflight"),
    )
    monkeypatch.setattr(
        commands,
        "create_async_engine",
        lambda *_args: pytest.fail("database must not be touched before live preflight"),
    )

    with pytest.raises(LivePreflightError, match="requires OPSFLOW_EVALUATION_LIVE_GEMINI=1"):
        run_evaluation(EvaluationMode.LIVE_GEMINI, environ={})
