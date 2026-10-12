"""Fail closed before integration tests can migrate or write application rows."""

import os

import pytest
from tests.integration_database_guard import (
    IntegrationDatabaseSafetyError,
    configure_integration_database,
    verify_integration_database_identity,
)

from opsflow.settings import Settings

try:
    _integration_database_url = configure_integration_database(
        os.environ,
        Settings().database_url,
    )
    verify_integration_database_identity(_integration_database_url)
except IntegrationDatabaseSafetyError as error:
    raise pytest.UsageError(str(error)) from error
