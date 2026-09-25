"""Environment settings validation tests for the Phase 8 review URL."""

import pytest
from pydantic import ValidationError

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
