"""Metadata contract tests for the Phase 2 persistence schema."""

from collections.abc import Iterable

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    MetaData,
    Numeric,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from opsflow.persistence.models import (
    AuditEventModel,
    Base,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)

EXPECTED_COLUMNS = {
    "orders": {
        "id",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "state",
        "failure_origin",
        "created_at",
    },
    "order_lines": {
        "id",
        "order_id",
        "position",
        "sku",
        "description",
        "quantity",
        "submitted_price",
        "trusted_catalogue_price",
    },
    "source_documents": {
        "id",
        "order_id",
        "position",
        "document_type",
        "name",
        "mime_type",
        "sha256",
        "message_id",
        "storage_reference",
        "metadata",
    },
    "validation_issues": {
        "order_id",
        "position",
        "rule_code",
        "severity",
        "field",
        "expected",
        "actual",
        "explanation",
    },
    "audit_events": {
        "id",
        "order_id",
        "event_type",
        "actor",
        "occurred_at",
        "description",
    },
    "order_creation_idempotency": {
        "idempotency_key",
        "request_fingerprint",
        "order_id",
        "created_at",
    },
}


def _normalized_checks(table: Table) -> set[str]:
    return {
        " ".join(str(constraint.sqltext).lower().split())
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _column_sets(constraints: Iterable[UniqueConstraint | Index]) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in constraint.columns) for constraint in constraints}


def test_metadata_contains_exactly_the_six_phase_2_tables_and_columns() -> None:
    metadata = Base.metadata

    assert set(metadata.tables) == set(EXPECTED_COLUMNS)
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        assert set(metadata.tables[table_name].columns.keys()) == expected_columns


def test_named_models_map_to_the_six_phase_2_tables() -> None:
    assert {
        model.__table__.name
        for model in (
            OrderModel,
            OrderLineModel,
            SourceDocumentModel,
            ValidationIssueModel,
            AuditEventModel,
            OrderCreationIdempotencyModel,
        )
    } == set(EXPECTED_COLUMNS)


def test_primary_keys_match_the_relational_identity_contract() -> None:
    metadata = Base.metadata
    expected_primary_keys = {
        "orders": ("id",),
        "order_lines": ("id",),
        "source_documents": ("id",),
        "validation_issues": ("order_id", "position"),
        "audit_events": ("id",),
        "order_creation_idempotency": ("idempotency_key",),
    }

    for table_name, expected_primary_key in expected_primary_keys.items():
        table = metadata.tables[table_name]
        assert tuple(column.name for column in table.primary_key.columns) == expected_primary_key


def test_children_and_idempotency_rows_have_the_required_foreign_keys() -> None:
    metadata = Base.metadata
    expected_on_delete = {
        "order_lines": "CASCADE",
        "source_documents": "CASCADE",
        "validation_issues": "CASCADE",
        "audit_events": "CASCADE",
        "order_creation_idempotency": "RESTRICT",
    }

    for table_name, on_delete in expected_on_delete.items():
        foreign_keys = list(metadata.tables[table_name].foreign_keys)
        assert len(foreign_keys) == 1
        assert foreign_keys[0].parent.name == "order_id"
        assert foreign_keys[0].target_fullname == "orders.id"
        assert foreign_keys[0].ondelete == on_delete


def test_ordered_children_have_stable_positions_and_required_access_paths() -> None:
    metadata = Base.metadata

    for table_name in ("order_lines", "source_documents"):
        table = metadata.tables[table_name]
        unique_columns = _column_sets(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        )
        assert ("order_id", "position") in unique_columns
        assert _column_sets(table.indexes) == {("order_id",)}

    validation_issues = metadata.tables["validation_issues"]
    assert _column_sets(validation_issues.indexes) == set()


def test_audit_and_idempotency_constraints_support_current_reads_and_uniqueness() -> None:
    metadata = Base.metadata
    audit_events = metadata.tables["audit_events"]
    idempotency = metadata.tables["order_creation_idempotency"]

    assert _column_sets(audit_events.indexes) == {("order_id", "occurred_at", "id")}
    assert _column_sets(idempotency.indexes) == set()
    unique_columns = _column_sets(
        constraint
        for constraint in idempotency.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert unique_columns == {("order_id",)}


def test_columns_use_the_required_postgresql_storage_types_and_nullability() -> None:
    metadata = Base.metadata

    for table_name in ("orders", "order_lines", "source_documents", "audit_events"):
        assert isinstance(metadata.tables[table_name].c.id.type, UUID)

    assert isinstance(metadata.tables["validation_issues"].c.order_id.type, UUID)
    assert isinstance(metadata.tables["order_creation_idempotency"].c.order_id.type, UUID)
    assert isinstance(metadata.tables["order_lines"].c.quantity.type, Numeric)
    assert isinstance(metadata.tables["order_lines"].c.submitted_price.type, Numeric)
    assert isinstance(metadata.tables["order_lines"].c.trusted_catalogue_price.type, Numeric)
    assert isinstance(metadata.tables["source_documents"].c.metadata.type, JSONB)
    assert isinstance(metadata.tables["validation_issues"].c.expected.type, JSONB)
    assert isinstance(metadata.tables["validation_issues"].c.actual.type, JSONB)
    fingerprint_type = metadata.tables["order_creation_idempotency"].c.request_fingerprint.type
    assert isinstance(fingerprint_type, CHAR)
    assert fingerprint_type.length == 64

    for table_name, column_name in (
        ("orders", "created_at"),
        ("audit_events", "occurred_at"),
        ("order_creation_idempotency", "created_at"),
    ):
        column_type = metadata.tables[table_name].c[column_name].type
        assert isinstance(column_type, DateTime)
        assert column_type.timezone is True

    orders = metadata.tables["orders"]
    for nullable_column in (
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "failure_origin",
    ):
        assert orders.c[nullable_column].nullable is True
    assert orders.c.state.nullable is False
    assert orders.c.created_at.nullable is False


def test_orders_encode_state_currency_and_failure_origin_checks() -> None:
    checks = _normalized_checks(Base.metadata.tables["orders"])
    all_states = {
        "received",
        "processing",
        "extracted",
        "validated",
        "needs_review",
        "ready_for_approval",
        "approved",
        "syncing",
        "completed",
        "rejected",
        "failed_retryable",
        "failed_final",
    }

    assert any(
        "state in" in check and all(state in check for state in all_states) for check in checks
    )
    assert any(
        "currency is null" in check
        and "currency" in check
        and "~ '^[a-z]{3}$'" in check
        and 'collate "c"' in check
        for check in checks
    )
    assert any(
        "failed_retryable" in check
        and "failed_final" in check
        and "processing" in check
        and "extracted" in check
        and "syncing" in check
        and "failure_origin is null" in check
        for check in checks
    )


def test_child_tables_encode_allowed_values_positions_numerics_hashes_and_json_shape() -> None:
    line_checks = _normalized_checks(Base.metadata.tables["order_lines"])
    document_checks = _normalized_checks(Base.metadata.tables["source_documents"])
    issue_checks = _normalized_checks(Base.metadata.tables["validation_issues"])

    assert any("position >= 0" in check for check in line_checks)
    assert any("quantity > 0" in check for check in line_checks)
    assert any("submitted_price >= 0" in check for check in line_checks)
    assert any("trusted_catalogue_price >= 0" in check for check in line_checks)

    assert any("position >= 0" in check for check in document_checks)
    assert any(
        "document_type in" in check
        and all(value in check for value in ("email_body", "pdf", "xlsx", "csv", "form"))
        for check in document_checks
    )
    assert any(
        "sha256" in check and "{64}" in check and 'collate "c"' in check
        for check in document_checks
    )
    assert any("jsonb_typeof(metadata) = 'array'" in check for check in document_checks)

    assert any("position >= 0" in check for check in issue_checks)
    assert any(
        "severity in" in check and all(value in check for value in ("info", "warning", "error"))
        for check in issue_checks
    )


def test_idempotency_values_have_bounded_key_and_lowercase_sha256_checks() -> None:
    checks = _normalized_checks(Base.metadata.tables["order_creation_idempotency"])

    assert any(
        "length(btrim(idempotency_key)) > 0" in check and "length(idempotency_key) <= 128" in check
        for check in checks
    )
    assert any(
        "request_fingerprint" in check and "^[0-9a-f]{64}$" in check and 'collate "c"' in check
        for check in checks
    )


def test_metadata_has_no_processing_attempt_table_or_custom_enum_type() -> None:
    metadata: MetaData = Base.metadata

    assert "processing_attempts" not in metadata.tables
    assert "processing_attempt" not in metadata.tables
    assert all(
        not isinstance(column.type, Enum)
        for table in metadata.tables.values()
        for column in table.columns
    )
