"""Environment settings validation tests for the Phase 8 review URL."""

import pytest
from pydantic import SecretStr, ValidationError

import opsflow.database as database_module
from opsflow.review import OperatorRole
from opsflow.settings import Settings


def test_review_base_url_defaults_to_local_review_origin() -> None:
    settings = Settings(_env_file=None)

    assert settings.review_base_url == "http://localhost:5173"


@pytest.mark.parametrize(
    "review_base_url",
    [
        "/review",
        "ftp://example.test",
        "javascript:alert(1)",
        "http://user:pass@example.test",
        "https://example.test?secret=value",
        "https://example.test#secret",
        "https://ops.example.test/app",
        "https://ops.example.test/app/",
        "https://ops.example.test///",
        "https://ops.example.test/review",
        "x" * 2_049,
    ],
)
def test_review_base_url_rejects_invalid_or_unsafe_values(review_base_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, review_base_url=review_base_url)


@pytest.mark.parametrize(
    "review_base_url",
    [
        "http://localhost:5173",
        "http://localhost:5173/",
        "https://ops.example.test",
        "https://ops.example.test/",
    ],
)
def test_review_base_url_accepts_absolute_http_and_https(
    review_base_url: str,
) -> None:
    settings = Settings(_env_file=None, review_base_url=review_base_url)

    assert settings.review_base_url == review_base_url.rstrip("/")


def test_review_base_url_accepts_exact_2_048_character_limit() -> None:
    host_labels = ["x" * 63 for _ in range(31)] + ["x" * 56]
    review_base_url = "https://" + ".".join(host_labels)
    assert len(review_base_url) == 2_048

    settings = Settings(_env_file=None, review_base_url=review_base_url)

    assert len(settings.review_base_url) == 2_048


@pytest.mark.parametrize(
    "role",
    [OperatorRole.REVIEWER, OperatorRole.APPROVER, OperatorRole.ELEVATED_APPROVER],
)
def test_orchestration_token_must_differ_from_every_review_capable_operator(
    role: OperatorRole,
) -> None:
    shared_token = "synthetic-shared-orchestration-review-token"

    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            orchestration_token=shared_token,
            review_dev_operators=(
                {
                    "token": shared_token,
                    "actor": "synthetic-human",
                    "role": role,
                },
            ),
        )

    assert "orchestration_token" in str(raised.value)
    assert "review_dev_operators" in str(raised.value)
    assert shared_token not in str(raised.value)


def test_distinct_orchestration_and_review_tokens_are_accepted() -> None:
    settings = Settings(
        _env_file=None,
        orchestration_token="synthetic-orchestration-token",
        review_dev_operators=(
            {
                "token": "synthetic-reviewer-token",
                "actor": "synthetic-reviewer",
                "role": OperatorRole.REVIEWER,
            },
            {
                "token": "synthetic-approver-token",
                "actor": "synthetic-approver",
                "role": OperatorRole.APPROVER,
            },
            {
                "token": "synthetic-elevated-approver-token",
                "actor": "synthetic-elevated-approver",
                "role": OperatorRole.ELEVATED_APPROVER,
            },
        ),
    )

    assert settings.orchestration_token is not None
    assert len(settings.review_dev_operators) == 3


def test_odoo_settings_are_optional_but_complete_when_present() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.odoo_base_url is None
    assert defaults.odoo_database is None
    assert defaults.odoo_api_key is None
    assert defaults.odoo_company_id is None
    assert defaults.odoo_warehouse_id is None
    assert defaults.odoo_pricelist_id is None

    configured = Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key="test-key",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
    )
    assert configured.odoo_base_url == "http://odoo.test"
    assert configured.odoo_database == "opsflow_test"
    assert configured.odoo_api_key is not None
    assert configured.odoo_company_id == 1
    assert configured.odoo_warehouse_id == 2
    assert configured.odoo_pricelist_id == 3

    with pytest.raises(ValidationError):
        Settings(_env_file=None, odoo_api_key="test-key")

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            odoo_base_url="http://odoo.test",
            odoo_database="opsflow_test",
            odoo_api_key="test-key",
            odoo_company_id=0,
            odoo_warehouse_id=2,
            odoo_pricelist_id=3,
        )


def test_odoo_api_key_is_secret_and_never_rendered() -> None:
    key = "distinctive-odoo-api-key-sentinel"
    settings = Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key=key,
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
    )

    assert key not in repr(settings)
    assert key not in str(settings)
    assert settings.odoo_api_key is not None
    assert settings.odoo_api_key.get_secret_value() == key


def test_gemini_api_key_is_secret_and_never_rendered() -> None:
    key = "synthetic-gemini-config-value"
    settings = Settings(_env_file=None, gemini_api_key=key)

    assert key not in repr(settings)
    assert key not in str(settings)
    assert isinstance(settings.gemini_api_key, SecretStr)
    assert settings.gemini_api_key.get_secret_value() == key


def test_database_url_is_not_rendered_but_remains_exact() -> None:
    database_url = (
        "postgresql+asyncpg://synthetic_user:synthetic_password@localhost:5432/synthetic_db"
    )
    settings = Settings(_env_file=None, database_url=database_url)

    assert database_url not in repr(settings)
    assert database_url not in str(settings)
    assert "synthetic_password" not in repr(settings)
    assert settings.database_url == database_url


def test_create_engine_receives_the_exact_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = (
        "postgresql+asyncpg://synthetic_user:synthetic_password@localhost:5432/synthetic_db"
    )
    captured: dict[str, object] = {}
    engine = object()

    def fake_create_async_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return engine

    monkeypatch.setattr(database_module, "create_async_engine", fake_create_async_engine)

    assert (
        database_module.create_engine(Settings(_env_file=None, database_url=database_url)) is engine
    )
    assert captured == {"url": database_url, "kwargs": {"pool_pre_ping": True}}


@pytest.mark.parametrize("gemini_api_key", [None, "", "   "])
def test_blank_gemini_api_key_is_unconfigured(gemini_api_key: str | None) -> None:
    settings = Settings(_env_file=None, gemini_api_key=gemini_api_key)

    assert settings.gemini_api_key is None


def test_secret_is_not_rendered_in_configuration_validation_errors() -> None:
    key = "SECRET_SENTINEL_DO_NOT_ECHO"

    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, odoo_api_key=key)

    assert key not in str(raised.value)


def test_hubspot_settings_are_optional_but_complete_when_present() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.hubspot_service_key is None
    assert defaults.hubspot_pipeline_id is None
    assert defaults.hubspot_initial_stage_id is None
    assert defaults.hubspot_portal_currency is None
    assert defaults.hubspot_expected_portal_id is None

    configured = Settings(
        _env_file=None,
        hubspot_service_key="test-hubspot-key",
        hubspot_pipeline_id="default",
        hubspot_initial_stage_id="appointmentscheduled",
        hubspot_portal_currency="USD",
        hubspot_expected_portal_id=149461984,
    )
    assert configured.hubspot_service_key is not None
    assert configured.hubspot_service_key.get_secret_value() == "test-hubspot-key"
    assert configured.hubspot_pipeline_id == "default"
    assert configured.hubspot_initial_stage_id == "appointmentscheduled"
    assert configured.hubspot_portal_currency == "USD"
    assert configured.hubspot_expected_portal_id == 149461984


def test_hubspot_service_key_is_secret_and_config_is_bounded() -> None:
    key = "distinctive-hubspot-api-key-sentinel"
    settings = Settings(
        _env_file=None,
        hubspot_service_key=key,
        hubspot_pipeline_id="default",
        hubspot_initial_stage_id="appointmentscheduled",
        hubspot_portal_currency="USD",
        hubspot_expected_portal_id=149461984,
    )

    assert key not in repr(settings)
    assert key not in str(settings)
    assert settings.hubspot_service_key is not None
    assert settings.hubspot_service_key.get_secret_value() == key


@pytest.mark.parametrize(
    "overrides",
    [
        {"hubspot_service_key": "key"},
        {"hubspot_pipeline_id": "default"},
        {
            "hubspot_service_key": "key",
            "hubspot_pipeline_id": "default",
        },
        {"hubspot_initial_stage_id": "appointmentscheduled"},
        {"hubspot_portal_currency": "USD"},
        {"hubspot_expected_portal_id": 149461984},
    ],
)
def test_partial_hubspot_configuration_is_accepted_as_unavailable(
    overrides: dict[str, object],
) -> None:
    settings = Settings(_env_file=None, **overrides)

    for name in overrides:
        assert getattr(settings, name) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"hubspot_service_key": " "},
        {"hubspot_pipeline_id": " "},
        {"hubspot_pipeline_id": "x" * 129},
        {"hubspot_initial_stage_id": " "},
        {"hubspot_initial_stage_id": "x" * 129},
        {"hubspot_portal_currency": "usd"},
        {"hubspot_portal_currency": "US1"},
        {"hubspot_portal_currency": "USDD"},
        {"hubspot_expected_portal_id": 1},
        {"hubspot_expected_portal_id": " "},
        {"hubspot_expected_portal_id": True},
    ],
)
def test_invalid_hubspot_settings_are_rejected(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "hubspot_service_key": "test-hubspot-key",
        "hubspot_pipeline_id": "default",
        "hubspot_initial_stage_id": "appointmentscheduled",
        "hubspot_portal_currency": "USD",
        "hubspot_expected_portal_id": 149461984,
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
