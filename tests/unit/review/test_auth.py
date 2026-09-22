"""Development bearer resolution and fixed Phase 6 capability tests."""

import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

import opsflow.review.auth as auth_module
from opsflow.application.errors import ForbiddenError, UnauthenticatedError
from opsflow.domain import OrderState
from opsflow.review import OperatorContext, OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings


def _operators() -> tuple[DevelopmentOperatorConfig, ...]:
    return (
        DevelopmentOperatorConfig(
            token="fake-reviewer-credential", actor="reviewer-1", role="REVIEWER"
        ),
        DevelopmentOperatorConfig(
            token="fake-approver-credential", actor="approver-1", role="APPROVER"
        ),
        DevelopmentOperatorConfig(
            token="fake-elevated-credential", actor="approver-2", role="ELEVATED_APPROVER"
        ),
    )


def test_settings_parse_three_operators_and_mask_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = [
        {"token": "fake-reviewer-credential", "actor": "reviewer-1", "role": "REVIEWER"},
        {"token": "fake-approver-credential", "actor": "approver-1", "role": "APPROVER"},
        {
            "token": "fake-elevated-credential",
            "actor": "approver-2",
            "role": "ELEVATED_APPROVER",
        },
    ]
    monkeypatch.setenv("OPSFLOW_REVIEW_DEV_OPERATORS", json.dumps(configured))

    settings = Settings(_env_file=None)

    assert tuple(item.role for item in settings.review_dev_operators) == (
        OperatorRole.REVIEWER,
        OperatorRole.APPROVER,
        OperatorRole.ELEVATED_APPROVER,
    )
    assert all(item.token.get_secret_value() for item in settings.review_dev_operators)
    assert "fake-reviewer-credential" not in repr(settings)
    assert "**********" in repr(settings)


def test_blank_or_unset_operator_configuration_means_no_anonymous_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPSFLOW_REVIEW_DEV_OPERATORS", "  ")

    settings = Settings(_env_file=None)

    assert settings.review_dev_operators == ()
    with pytest.raises(UnauthenticatedError):
        auth_module.resolve_operator_token("any-credential", settings.review_dev_operators)


def test_settings_reject_duplicate_tokens_without_exposing_them() -> None:
    duplicate = (
        DevelopmentOperatorConfig(token="fake-duplicate", actor="reviewer", role="REVIEWER"),
        DevelopmentOperatorConfig(token="fake-duplicate", actor="approver", role="APPROVER"),
    )

    with pytest.raises(ValidationError) as error:
        Settings(review_dev_operators=duplicate)

    assert "fake-duplicate" not in str(error.value)


def test_malformed_operator_json_does_not_echo_raw_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_credential = "fake-malformed-config-credential"
    monkeypatch.setenv("OPSFLOW_REVIEW_DEV_OPERATORS", '[{"token":"' + fake_credential + '"')

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert fake_credential not in str(error.value)


@pytest.mark.parametrize(
    "record",
    [
        {"token": "fake-token", "actor": "  ", "role": "REVIEWER"},
        {"token": "fake-token", "actor": "a" * 129, "role": "REVIEWER"},
        {"token": "fake-token", "actor": "reviewer", "role": "SUPERUSER"},
        {"token": "  ", "actor": "reviewer", "role": "REVIEWER"},
        {"token": "fake-token", "actor": "reviewer", "role": "REVIEWER", "extra": "x"},
    ],
)
def test_development_operator_configuration_is_strict(record: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        DevelopmentOperatorConfig(**record)


def test_token_resolution_uses_constant_time_comparison_for_every_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _operators()
    comparison_count = 0
    compare = hmac.compare_digest

    def count_comparisons(first: bytes, second: bytes) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return compare(first, second)

    monkeypatch.setattr(auth_module.hmac, "compare_digest", count_comparisons)

    context = auth_module.resolve_operator_token("fake-approver-credential", configured)

    assert context == OperatorContext("approver-1", OperatorRole.APPROVER)
    assert comparison_count == len(configured)


def test_unknown_token_fails_with_one_safe_error() -> None:
    with pytest.raises(UnauthenticatedError) as error:
        auth_module.resolve_operator_token("unknown-credential", _operators())

    assert str(error.value) == "Development operator authentication is required."
    assert "unknown-credential" not in str(error.value)


def test_non_ascii_unknown_token_fails_safely() -> None:
    with pytest.raises(UnauthenticatedError):
        auth_module.resolve_operator_token("unknown-π", _operators())


def test_fastapi_bearer_dependency_ignores_client_actor_and_role_claims() -> None:
    configured = _operators()
    application = SimpleNamespace(state=SimpleNamespace(review_dev_operators=configured))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/review/orders",
            "raw_path": b"/v1/review/orders",
            "query_string": b"",
            "headers": [
                (b"x-actor", b"attacker"),
                (b"x-role", b"ELEVATED_APPROVER"),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "app": application,
        }
    )
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake-reviewer-credential")

    context = auth_module.get_operator_context(request, bearer)

    assert context == OperatorContext("reviewer-1", OperatorRole.REVIEWER)
    dependency = auth_module.get_operator_context.__defaults__[0]
    assert isinstance(dependency.dependency, HTTPBearer)
    assert dependency.dependency.auto_error is False


def test_fastapi_bearer_dependency_rejects_missing_credentials() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/review/orders",
            "raw_path": b"/v1/review/orders",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "app": SimpleNamespace(state=SimpleNamespace(review_dev_operators=_operators())),
        }
    )

    with pytest.raises(UnauthenticatedError):
        auth_module.get_operator_context(request, None)


@pytest.mark.parametrize(
    ("role", "capability", "state", "high_value", "allowed"),
    [
        (OperatorRole.REVIEWER, "view", OrderState.NEEDS_REVIEW, False, True),
        (OperatorRole.APPROVER, "view", OrderState.READY_FOR_APPROVAL, False, True),
        (OperatorRole.ELEVATED_APPROVER, "view", OrderState.FAILED_RETRYABLE, False, True),
        (OperatorRole.REVIEWER, "review", OrderState.NEEDS_REVIEW, False, True),
        (OperatorRole.APPROVER, "review", OrderState.NEEDS_REVIEW, False, False),
        (OperatorRole.APPROVER, "approve", OrderState.READY_FOR_APPROVAL, False, True),
        (OperatorRole.APPROVER, "approve", OrderState.READY_FOR_APPROVAL, True, False),
        (OperatorRole.ELEVATED_APPROVER, "approve", OrderState.READY_FOR_APPROVAL, False, True),
        (OperatorRole.ELEVATED_APPROVER, "approve", OrderState.READY_FOR_APPROVAL, True, True),
        (OperatorRole.REVIEWER, "approve", OrderState.READY_FOR_APPROVAL, False, False),
        (OperatorRole.REVIEWER, "reject", OrderState.NEEDS_REVIEW, False, True),
        (OperatorRole.APPROVER, "reject", OrderState.READY_FOR_APPROVAL, True, True),
        (OperatorRole.APPROVER, "reject", OrderState.NEEDS_REVIEW, False, False),
        (OperatorRole.ELEVATED_APPROVER, "reject", OrderState.READY_FOR_APPROVAL, True, True),
        (OperatorRole.REVIEWER, "retry", OrderState.FAILED_RETRYABLE, False, True),
        (OperatorRole.APPROVER, "retry", OrderState.FAILED_RETRYABLE, False, False),
    ],
)
def test_fixed_capability_matrix(
    role: OperatorRole,
    capability: str,
    state: OrderState,
    high_value: bool,
    allowed: bool,
) -> None:
    context = OperatorContext("operator", role)
    check = {
        "view": lambda: auth_module.require_view_access(context),
        "review": lambda: auth_module.require_reviewer(context),
        "approve": lambda: auth_module.require_approval(context, high_value=high_value),
        "reject": lambda: auth_module.require_rejection(context, state),
        "retry": lambda: auth_module.require_retry(context),
    }[capability]

    if allowed:
        check()
    else:
        with pytest.raises(ForbiddenError):
            check()
