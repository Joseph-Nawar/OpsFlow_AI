"""Environment-driven application settings."""

import json
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
        try:
            parsed = TypeAdapter(AnyHttpUrl).validate_python(value)
        except ValidationError as error:
            raise ValueError("review base URL must be an absolute HTTP or HTTPS URL") from error
        return str(parsed).rstrip("/")

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
