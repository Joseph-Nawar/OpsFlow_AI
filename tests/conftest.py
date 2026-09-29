"""Shared safety fixtures for database integration tests."""

import os

import pytest
from sqlalchemy.engine import make_url

from opsflow.settings import Settings


@pytest.fixture
def migration_test_database_url() -> str:
    """Require destructive migration tests to use a separate PostgreSQL DB."""

    configured_url = os.environ.get("OPSFLOW_MIGRATION_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("isolated migration database is not configured")

    try:
        migration_url = make_url(configured_url)
        development_url = make_url(Settings().database_url)
    except Exception:
        pytest.fail("migration database configuration must contain valid database URLs")

    if migration_url.get_backend_name() != "postgresql":
        pytest.fail("isolated migration database must use PostgreSQL")
    if not migration_url.database:
        pytest.fail("isolated migration database must name a database")
    if migration_url.database == development_url.database:
        pytest.fail("migration test database must differ from development database")

    return configured_url
