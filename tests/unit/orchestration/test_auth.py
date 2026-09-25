import inspect

import pytest
from fastapi import FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr

from opsflow.application.errors import OrchestrationUnauthenticatedError
from opsflow.orchestration import auth as orchestration_auth
from opsflow.orchestration.auth import (
    ORCHESTRATION_ACTOR,
    get_orchestration_actor,
    resolve_orchestration_token,
)
from opsflow.settings import Settings


def _request(configured: SecretStr | None, headers: dict[str, str] | None = None) -> Request:
    app = FastAPI()
    app.state.orchestration_token = configured
    encoded_headers = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/orchestration/intakes",
            "headers": encoded_headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "app": app,
        }
    )


def _credentials(token: str, scheme: str = "Bearer") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme=scheme, credentials=token)


def test_settings_parses_orchestration_token_as_masked_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "task-1-orchestration-token"
    monkeypatch.setenv("OPSFLOW_ORCHESTRATION_TOKEN", token)

    settings = Settings(_env_file=None)

    assert isinstance(settings.orchestration_token, SecretStr)
    assert settings.orchestration_token.get_secret_value() == token
    assert str(settings.orchestration_token) == "**********"
    assert token not in repr(settings)


def test_settings_allows_missing_orchestration_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPSFLOW_ORCHESTRATION_TOKEN", raising=False)

    settings = Settings(_env_file=None)

    assert settings.orchestration_token is None


def test_resolver_returns_only_fixed_orchestration_actor() -> None:
    assert resolve_orchestration_token("configured", SecretStr("configured")) == ORCHESTRATION_ACTOR


@pytest.mark.parametrize(
    ("token", "configured"),
    [
        ("configured", None),
        ("configured", SecretStr("")),
        ("configured", SecretStr("   ")),
        ("", SecretStr("configured")),
        ("   ", SecretStr("configured")),
        ("wrong", SecretStr("configured")),
    ],
)
def test_resolver_fails_closed_for_missing_blank_or_wrong_secrets(
    token: str, configured: SecretStr | None
) -> None:
    with pytest.raises(OrchestrationUnauthenticatedError) as error:
        resolve_orchestration_token(token, configured)

    assert str(error.value) == "Orchestration service authentication is required."


def test_dependency_rejects_missing_credentials() -> None:
    with pytest.raises(OrchestrationUnauthenticatedError):
        get_orchestration_actor(_request(SecretStr("configured")), None)


def test_dependency_rejects_non_bearer_credentials() -> None:
    with pytest.raises(OrchestrationUnauthenticatedError):
        get_orchestration_actor(
            _request(SecretStr("configured")), _credentials("configured", scheme="Basic")
        )


def test_dependency_rejects_blank_presented_token() -> None:
    with pytest.raises(OrchestrationUnauthenticatedError) as error:
        get_orchestration_actor(_request(SecretStr("configured")), _credentials(""))

    assert str(error.value) == "Orchestration service authentication is required."


def test_dependency_returns_fixed_actor_for_valid_bearer() -> None:
    actor = get_orchestration_actor(_request(SecretStr("configured")), _credentials("configured"))

    assert actor == "orchestration:n8n"


def test_dependency_ignores_caller_identity_headers() -> None:
    actor = get_orchestration_actor(
        _request(
            SecretStr("configured"),
            {
                "X-Actor": "reviewer:human",
                "X-Role": "elevated_approver",
                "X-Machine-Actor": "caller-selected-machine",
                "X-Selector": "arbitrary-authority",
            },
        ),
        _credentials("configured"),
    )

    assert actor == ORCHESTRATION_ACTOR


def test_dependency_does_not_extract_body_or_caller_authority_claims() -> None:
    source = inspect.getsource(orchestration_auth.get_orchestration_actor)

    assert "request.body" not in source
    assert "X-Actor" not in source
    assert "X-Role" not in source
    assert "actor" not in source.lower().replace("orchestration_actor", "")
    assert "role" not in source.lower()


def test_authentication_errors_never_include_credential_values() -> None:
    configured = "server-secret-value"
    presented = "caller-secret-value"

    with pytest.raises(OrchestrationUnauthenticatedError) as error:
        resolve_orchestration_token(presented, SecretStr(configured))

    assert configured not in str(error.value)
    assert presented not in str(error.value)
    assert configured not in repr(error.value)
    assert presented not in repr(error.value)


def test_resolver_uses_one_constant_time_utf8_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    original_compare_digest = orchestration_auth.hmac.compare_digest

    def record_compare_digest(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(orchestration_auth.hmac, "compare_digest", record_compare_digest)

    assert resolve_orchestration_token("café", SecretStr("café")) == ORCHESTRATION_ACTOR
    assert calls == [("café".encode(), "café".encode())]
