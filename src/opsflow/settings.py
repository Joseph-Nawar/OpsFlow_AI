"""Environment-driven application settings."""

import json
import re
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from opsflow.review import OperatorRole


class DevelopmentOperatorConfig(BaseModel):
    """One explicitly configured local development operator credential."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    token: SecretStr
    actor: str
    role: OperatorRole

    @field_validator("token")
    @classmethod
    def require_nonblank_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("development operator token must be nonblank")
        return value

    @field_validator("actor", mode="before")
    @classmethod
    def require_string_actor(cls, value: object) -> object:
        if type(value) is not str:
            raise ValueError("development operator actor must be a string")
        return value

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        if not value.strip() or len(value) > 128:
            raise ValueError(
                "development operator actor must be nonblank and at most 128 characters"
            )
        return value


class Settings(BaseSettings):
    """Runtime settings with safe local-development defaults."""

    database_url: str = "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow"
    orchestration_token: SecretStr | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_timeout_seconds: float | None = None
    review_base_url: str = "http://localhost:5173"
    review_dev_operators: Annotated[tuple[DevelopmentOperatorConfig, ...], NoDecode] = ()
    odoo_base_url: str | None = None
    odoo_database: str | None = None
    odoo_api_key: SecretStr | None = None
    odoo_company_id: int | None = None
    odoo_warehouse_id: int | None = None
    odoo_pricelist_id: int | None = None
    hubspot_service_key: SecretStr | None = None
    hubspot_pipeline_id: str | None = None
    hubspot_initial_stage_id: str | None = None
    hubspot_portal_currency: str | None = None
    hubspot_expected_portal_id: int | None = None

    @field_validator("review_base_url", mode="before")
    @classmethod
    def validate_review_base_url(cls, value: object) -> str:
        if type(value) is not str or not value.strip() or value != value.strip():
            raise ValueError("review base URL must be a nonblank absolute HTTP or HTTPS URL")
        if len(value) > 2_048:
            raise ValueError("review base URL must be at most 2,048 characters")
        components = urlsplit(value)
        if "@" in components.netloc or "?" in value or "#" in value:
            raise ValueError("review base URL cannot contain credentials, query, or fragment")
        if components.path not in ("", "/"):
            raise ValueError("review base URL must not contain a path")
        try:
            parsed = TypeAdapter(AnyHttpUrl).validate_python(value)
        except ValidationError as error:
            raise ValueError("review base URL must be an absolute HTTP or HTTPS URL") from error
        return str(parsed).rstrip("/")

    @field_validator("odoo_base_url", mode="before")
    @classmethod
    def validate_odoo_base_url(cls, value: object) -> str | None:
        if value is None:
            return None
        if type(value) is str and not value.strip():
            return None
        if type(value) is not str or not value.strip() or value != value.strip():
            raise ValueError("Odoo base URL must be a nonblank absolute HTTP or HTTPS URL")
        if len(value) > 2_048:
            raise ValueError("Odoo base URL must be at most 2,048 characters")
        components = urlsplit(value)
        if "@" in components.netloc or "?" in value or "#" in value:
            raise ValueError("Odoo base URL cannot contain credentials, query, or fragment")
        if components.path not in ("", "/"):
            raise ValueError("Odoo base URL must not contain a path")
        try:
            parsed = TypeAdapter(AnyHttpUrl).validate_python(value)
        except ValidationError as error:
            raise ValueError("Odoo base URL must be an absolute HTTP or HTTPS URL") from error
        return str(parsed).rstrip("/")

    @field_validator("odoo_database", mode="before")
    @classmethod
    def validate_odoo_database(cls, value: object) -> str | None:
        if value is None:
            return None
        if type(value) is str and not value.strip():
            return None
        if (
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            or len(value) > 128
        ):
            raise ValueError("Odoo database must be a nonblank name of at most 128 characters")
        return value

    @field_validator("odoo_api_key", mode="before")
    @classmethod
    def validate_odoo_api_key(cls, value: object) -> object:
        if value is None or (type(value) is str and not value.strip()):
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @field_validator("odoo_company_id", "odoo_warehouse_id", "odoo_pricelist_id", mode="before")
    @classmethod
    def reject_boolean_odoo_ids(cls, value: object) -> object:
        if type(value) is str and not value.strip():
            return None
        if type(value) is bool:
            raise ValueError("Odoo IDs must be positive integers")
        return value

    @field_validator("odoo_company_id", "odoo_warehouse_id", "odoo_pricelist_id")
    @classmethod
    def require_positive_odoo_ids(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Odoo IDs must be positive integers")
        return value

    @field_validator("hubspot_service_key", mode="before")
    @classmethod
    def validate_hubspot_service_key(cls, value: object) -> object:
        if value is None or (type(value) is str and not value.strip()):
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @field_validator("hubspot_pipeline_id", "hubspot_initial_stage_id", mode="before")
    @classmethod
    def validate_hubspot_identifiers(cls, value: object) -> str | None:
        if value is None or (type(value) is str and not value.strip()):
            return None
        if type(value) is not str or value != value.strip() or len(value) > 128:
            raise ValueError("HubSpot identifiers must be nonblank strings up to 128 characters")
        return value

    @field_validator("hubspot_portal_currency", mode="before")
    @classmethod
    def validate_hubspot_portal_currency(cls, value: object) -> str | None:
        if value is None or (type(value) is str and not value.strip()):
            return None
        if type(value) is not str or re.fullmatch(r"[A-Z]{3}", value, flags=re.ASCII) is None:
            raise ValueError("HubSpot portal currency must be an uppercase ISO code")
        return value

    @field_validator("hubspot_expected_portal_id", mode="before")
    @classmethod
    def validate_hubspot_expected_portal_id(cls, value: object) -> object:
        if value is None or (type(value) is str and not value.strip()):
            return None
        if type(value) is bool:
            raise ValueError("HubSpot expected portal ID must match the verified test portal")
        return value

    @field_validator("hubspot_expected_portal_id")
    @classmethod
    def require_verified_hubspot_portal(cls, value: int | None) -> int | None:
        if value is not None and value != 149461984:
            raise ValueError("HubSpot expected portal ID must match the verified test portal")
        return value

    @field_validator("review_dev_operators", mode="before")
    @classmethod
    def parse_review_dev_operators(cls, value: object) -> object:
        if value is None or (type(value) is str and not value.strip()):
            return ()
        if type(value) is str:
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("review development operators must be a JSON array") from error
        if isinstance(value, list):
            return tuple(value)
        if isinstance(value, tuple):
            return value
        raise ValueError("review development operators must be a JSON array")

    @model_validator(mode="after")
    def require_unique_review_operator_tokens(self) -> "Settings":
        tokens = tuple(operator.token.get_secret_value() for operator in self.review_dev_operators)
        if len(set(tokens)) != len(tokens):
            raise ValueError("review development operator tokens must be unique")
        odoo_values = (
            self.odoo_base_url,
            self.odoo_database,
            self.odoo_api_key,
            self.odoo_company_id,
            self.odoo_warehouse_id,
            self.odoo_pricelist_id,
        )
        if any(value is not None for value in odoo_values) and any(
            value is None for value in odoo_values
        ):
            raise ValueError("all Odoo settings must be configured together")
        hubspot_values = (
            self.hubspot_service_key,
            self.hubspot_pipeline_id,
            self.hubspot_initial_stage_id,
            self.hubspot_portal_currency,
            self.hubspot_expected_portal_id,
        )
        if any(value is not None for value in hubspot_values) and any(
            value is None for value in hubspot_values
        ):
            raise ValueError("all HubSpot settings must be configured together")
        return self

    model_config = SettingsConfigDict(
        env_prefix="OPSFLOW_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Load and cache application settings."""

    return Settings()
