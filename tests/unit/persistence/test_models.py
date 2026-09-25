"""Metadata contract tests for the relational persistence schema."""

import re
from collections.abc import Iterable

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
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
    ExtractionSnapshotModel,
    NotificationDeliveryModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    ReviewRevisionModel,
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
    "extraction_snapshots": {
        "id",
        "order_id",
        "source_document_id",
        "source_sha256",
        "source_document_type",
        "payload",
        "created_at",
    },
    "review_revisions": {
        "id",
        "order_id",
        "extraction_snapshot_id",
        "revision_number",
        "payload",
        "changes",
        "actor",
        "created_at",
    },
    "notification_deliveries": {
        "id",
        "order_id",
        "trigger_audit_event_id",
        "channel",
        "kind",
        "payload",
        "status",
        "attempt_count",
        "claim_token",
        "claim_expires_at",
        "next_attempt_at",
        "provider_reference",
        "last_failure_code",
        "created_at",
        "updated_at",
    },
}


def _normalized_checks(table: Table) -> set[str]:
    return {
        " ".join(str(constraint.sqltext).lower().split())
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _named_check(table: Table, name: str) -> str:
    matches = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert len(matches) == 1
    return " ".join(str(matches[0].sqltext).split())


def _in_values(check_sql: str, column_name: str) -> set[str]:
    match = re.search(
        rf"\b{re.escape(column_name)}\s+IN\s+\(([^)]*)\)", check_sql, flags=re.IGNORECASE
    )
    assert match is not None
    return {value.strip().strip("'") for value in match.group(1).split(",")}


def _column_sets(constraints: Iterable[UniqueConstraint | Index]) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in constraint.columns) for constraint in constraints}


def test_metadata_contains_exact_tables_and_columns() -> None:
    metadata = Base.metadata

    assert set(metadata.tables) == set(EXPECTED_COLUMNS)
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        assert set(metadata.tables[table_name].columns.keys()) == expected_columns


def test_named_models_map_to_the_expected_relational_tables() -> None:
    assert {
        model.__table__.name
        for model in (
            OrderModel,
            OrderLineModel,
            SourceDocumentModel,
            ValidationIssueModel,
            AuditEventModel,
            OrderCreationIdempotencyModel,
            ExtractionSnapshotModel,
            ReviewRevisionModel,
            NotificationDeliveryModel,
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
        "extraction_snapshots": ("id",),
        "review_revisions": ("id",),
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

    snapshot_foreign_keys = list(metadata.tables["extraction_snapshots"].foreign_keys)
    assert {
        (foreign_key.parent.name, foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in snapshot_foreign_keys
    } == {
        ("order_id", "orders.id", "CASCADE"),
        ("source_document_id", "source_documents.id", "CASCADE"),
        ("order_id", "source_documents.order_id", "CASCADE"),
    }


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
        assert _column_sets(table.indexes) == set()

    validation_issues = metadata.tables["validation_issues"]
    assert _column_sets(validation_issues.indexes) == set()


def test_audit_and_idempotency_constraints_support_current_reads_and_uniqueness() -> None:
    metadata = Base.metadata
    audit_events = metadata.tables["audit_events"]
    idempotency = metadata.tables["order_creation_idempotency"]

    assert _column_sets(metadata.tables["orders"].indexes) == set()
    assert _column_sets(audit_events.indexes) == {("order_id", "occurred_at", "id")}
    assert _column_sets(idempotency.indexes) == set()
    unique_columns = _column_sets(
        constraint
        for constraint in idempotency.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert unique_columns == {("order_id",)}

    snapshots = metadata.tables["extraction_snapshots"]
    snapshot_indexes = list(snapshots.indexes)
    assert _column_sets(snapshot_indexes) == {("source_sha256",)}
    assert [index.name for index in snapshot_indexes] == ["ix_extraction_snapshots_source_sha256"]
    assert {
        constraint.name
        for constraint in snapshots.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        "uq_extraction_snapshots_order_source",
        "uq_extraction_snapshots_id_order_id",
    }


def test_columns_use_the_required_postgresql_storage_types_and_nullability() -> None:
    metadata = Base.metadata

    for table_name in ("orders", "order_lines", "source_documents", "audit_events"):
        assert isinstance(metadata.tables[table_name].c.id.type, UUID)

    assert isinstance(metadata.tables["validation_issues"].c.order_id.type, UUID)
    assert isinstance(metadata.tables["order_creation_idempotency"].c.order_id.type, UUID)
    for column_name in ("quantity", "submitted_price", "trusted_catalogue_price"):
        numeric_type = metadata.tables["order_lines"].c[column_name].type
        assert isinstance(numeric_type, Numeric)
        assert numeric_type.precision is None
        assert numeric_type.scale is None
    assert isinstance(metadata.tables["source_documents"].c.metadata.type, JSONB)
    assert isinstance(metadata.tables["validation_issues"].c.expected.type, JSONB)
    assert isinstance(metadata.tables["validation_issues"].c.actual.type, JSONB)
    assert isinstance(metadata.tables["extraction_snapshots"].c.payload.type, JSONB)
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

    snapshots = metadata.tables["extraction_snapshots"]
    assert snapshots.c.id.nullable is False
    assert snapshots.c.order_id.nullable is False
    assert snapshots.c.source_document_id.nullable is False
    assert snapshots.c.source_sha256.nullable is False
    assert snapshots.c.source_document_type.nullable is False
    assert snapshots.c.payload.nullable is False
    assert snapshots.c.created_at.nullable is False
    assert snapshots.c.id.server_default is None
    assert snapshots.c.created_at.server_default is None
    assert snapshots.c.created_at.type.timezone is True


def test_orders_encode_state_currency_and_failure_origin_checks() -> None:
    orders = Base.metadata.tables["orders"]
    checks = _normalized_checks(orders)
    expected_states = {
        "RECEIVED",
        "PROCESSING",
        "EXTRACTED",
        "VALIDATED",
        "NEEDS_REVIEW",
        "READY_FOR_APPROVAL",
        "APPROVED",
        "SYNCING",
        "COMPLETED",
        "REJECTED",
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
    }

    assert _in_values(_named_check(orders, "ck_orders_state"), "state") == expected_states
    assert any(
        "currency is null" in check
        and "currency" in check
        and "~ '^[a-z]{3}$'" in check
        and 'collate "c"' in check
        for check in checks
    )
    failure_check = _named_check(orders, "ck_orders_failure_origin").lower()
    assert "failure_origin is not null" in failure_check
    assert "failure_origin is null" in failure_check
    assert _in_values(failure_check, "failure_origin") == {
        "processing",
        "extracted",
        "syncing",
    }


def test_child_tables_encode_allowed_values_positions_numerics_hashes_and_json_shape() -> None:
    line_checks = _normalized_checks(Base.metadata.tables["order_lines"])
    document_checks = _normalized_checks(Base.metadata.tables["source_documents"])
    issue_checks = _normalized_checks(Base.metadata.tables["validation_issues"])

    assert any("position >= 0" in check for check in line_checks)
    assert any("quantity > 0" in check for check in line_checks)
    assert any("submitted_price >= 0" in check for check in line_checks)
    assert any("trusted_catalogue_price >= 0" in check for check in line_checks)

    assert any("position >= 0" in check for check in document_checks)
    assert _in_values(
        _named_check(Base.metadata.tables["source_documents"], "ck_source_documents_document_type"),
        "document_type",
    ) == {"EMAIL_BODY", "PDF", "XLSX", "CSV", "FORM"}
    assert any(
        "sha256" in check and "{64}" in check and 'collate "c"' in check
        for check in document_checks
    )
    assert any("jsonb_typeof(metadata) = 'array'" in check for check in document_checks)

    assert any("position >= 0" in check for check in issue_checks)
    assert _in_values(
        _named_check(Base.metadata.tables["validation_issues"], "ck_validation_issues_severity"),
        "severity",
    ) == {"INFO", "WARNING", "ERROR"}


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


def test_extraction_snapshot_checks_are_named_and_defense_in_depth_is_explicit() -> None:
    snapshots = Base.metadata.tables["extraction_snapshots"]
    assert {
        constraint.name
        for constraint in snapshots.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_extraction_snapshots_sha256",
        "ck_extraction_snapshots_document_type",
        "ck_extraction_snapshots_payload_object",
    }
    checks = _normalized_checks(snapshots)
    assert any("jsonb_typeof(payload) = 'object'" in check for check in checks)
    assert any("source_sha256" in check and "^[0-9a-f]{64}$" in check for check in checks)
    assert any("source_document_type" in check for check in checks)


def test_review_revision_metadata_locks_immutable_ownership_and_constraints() -> None:
    metadata = Base.metadata
    revisions = metadata.tables["review_revisions"]
    snapshots = metadata.tables["extraction_snapshots"]

    assert set(metadata.tables) == set(EXPECTED_COLUMNS)
    assert _column_sets(
        constraint
        for constraint in snapshots.constraints
        if isinstance(constraint, UniqueConstraint)
    ) == {("order_id", "source_document_id"), ("id", "order_id")}
    assert {
        tuple(column.name for column in constraint.columns)
        for constraint in revisions.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {("order_id", "revision_number")}
    foreign_keys = {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in revisions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys == {
        (("order_id",), ("orders.id",), "CASCADE"),
        (
            ("extraction_snapshot_id", "order_id"),
            ("extraction_snapshots.id", "extraction_snapshots.order_id"),
            "CASCADE",
        ),
    }
    assert {
        constraint.name
        for constraint in revisions.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_review_revisions_revision_positive",
        "ck_review_revisions_payload_object",
        "ck_review_revisions_changes_array",
        "ck_review_revisions_actor",
    }
    checks = _normalized_checks(revisions)
    assert any("revision_number > 0" in check for check in checks)
    assert any("jsonb_typeof(payload) = 'object'" in check for check in checks)
    assert any("jsonb_typeof(changes) = 'array'" in check for check in checks)
    assert any(
        "length(btrim(actor)) > 0" in check and "length(actor) <= 128" in check for check in checks
    )
    assert isinstance(revisions.c.payload.type, JSONB)
    assert isinstance(revisions.c.changes.type, JSONB)
    assert isinstance(revisions.c.created_at.type, DateTime)
    assert revisions.c.created_at.type.timezone is True
    assert revisions.c.created_at.nullable is False
    assert revisions.c.actor.nullable is False
    assert revisions.c.actor.type.length == 128
    assert "approval_level" not in revisions.columns
    assert not any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns) == ("source_sha256",)
        for constraint in snapshots.constraints
    )
