"""Bounded durable contracts for the Phase 9 order synchronization process."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from opsflow.domain import OrderState

_MAX_EXTERNAL_ID_LENGTH = 256
_MAX_ODOO_ORDER_NAME_LENGTH = 256


class OrderSyncStep(StrEnum):
    """Durable checkpoints for the approved Phase 9 provider sequence."""

    ODOO_LOOKUP = "ODOO_LOOKUP"
    ODOO_BRIDGE = "ODOO_BRIDGE"
    HUBSPOT_COMPANY = "HUBSPOT_COMPANY"
    HUBSPOT_DEAL = "HUBSPOT_DEAL"
    HUBSPOT_ASSOCIATION = "HUBSPOT_ASSOCIATION"


class OrderSyncFailureCode(StrEnum):
    """Allowlisted failure categories without provider diagnostics."""

    INTEGRATION_CONFIG = "INTEGRATION_CONFIG"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_INVALID_RESPONSE = "PROVIDER_INVALID_RESPONSE"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    TRUSTED_CUSTOMER_MISSING = "TRUSTED_CUSTOMER_MISSING"
    TRUSTED_CUSTOMER_AMBIGUOUS = "TRUSTED_CUSTOMER_AMBIGUOUS"
    TRUSTED_PRODUCT_MISSING = "TRUSTED_PRODUCT_MISSING"
    TRUSTED_PRODUCT_CHANGED = "TRUSTED_PRODUCT_CHANGED"
    INVENTORY_INSUFFICIENT = "INVENTORY_INSUFFICIENT"
    WORKER_LEASE_EXHAUSTED = "WORKER_LEASE_EXHAUSTED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ExecuteNextKind(StrEnum):
    """Sanitized outcome values returned by the single orchestration endpoint."""

    COMPLETED = "completed"
    WORKED = "worked"
    YIELDED = "yielded"
    NO_WORK = "no_work"
    RETRY_WAIT = "retry_wait"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True, slots=True)
class OrderSync:
    """Validated application representation of one durable order-sync row."""

    order_id: UUID
    claim_token: UUID | None
    claim_expires_at: datetime | None
    attempt_count: int
    retry_generation: int
    next_attempt_at: datetime
    odoo_sale_order_id: int | None
    odoo_sale_order_name: str | None
    hubspot_company_id: str | None
    hubspot_deal_id: str | None
    hubspot_association_confirmed_at: datetime | None
    in_flight_step: OrderSyncStep | None
    last_failure_step: OrderSyncStep | None
    last_failure_code: OrderSyncFailureCode | None
    last_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.order_id, "order_id")
        if self.claim_token is not None:
            _require_uuid(self.claim_token, "claim_token")
        if (self.claim_token is None) != (self.claim_expires_at is None):
            raise ValueError("claim_token and claim_expires_at must be both set or both empty")
        if self.claim_expires_at is not None:
            _require_aware(self.claim_expires_at, "claim_expires_at")
        if type(self.attempt_count) is not int or not 0 <= self.attempt_count <= 3:
            raise ValueError("attempt_count must be an integer from 0 through 3")
        if type(self.retry_generation) is not int or self.retry_generation < 0:
            raise ValueError("retry_generation must be a nonnegative integer")
        for name in ("next_attempt_at", "created_at", "updated_at"):
            _require_aware(getattr(self, name), name)
        if self.odoo_sale_order_id is not None and (
            type(self.odoo_sale_order_id) is not int or self.odoo_sale_order_id <= 0
        ):
            raise ValueError("odoo_sale_order_id must be a positive integer or None")
        if (self.odoo_sale_order_id is None) != (self.odoo_sale_order_name is None):
            raise ValueError("Odoo sale-order ID and name must be paired")
        if self.odoo_sale_order_name is not None:
            _require_bounded(
                self.odoo_sale_order_name,
                "odoo_sale_order_name",
                _MAX_ODOO_ORDER_NAME_LENGTH,
            )
        for name in ("hubspot_company_id", "hubspot_deal_id"):
            value = getattr(self, name)
            if value is not None:
                _require_bounded(value, name, _MAX_EXTERNAL_ID_LENGTH)
        if self.hubspot_association_confirmed_at is not None:
            _require_aware(
                self.hubspot_association_confirmed_at,
                "hubspot_association_confirmed_at",
            )
            if self.hubspot_company_id is None or self.hubspot_deal_id is None:
                raise ValueError("association receipt requires Company and Deal receipts")
        if self.in_flight_step is not None and not isinstance(self.in_flight_step, OrderSyncStep):
            raise ValueError("in_flight_step must be an OrderSyncStep or None")
        if self.last_failure_step is not None and not isinstance(
            self.last_failure_step, OrderSyncStep
        ):
            raise ValueError("last_failure_step must be an OrderSyncStep or None")
        if self.last_failure_code is not None and not isinstance(
            self.last_failure_code, OrderSyncFailureCode
        ):
            raise ValueError("last_failure_code must be an OrderSyncFailureCode or None")
        if (self.last_failure_step is None) != (self.last_failure_code is None):
            raise ValueError("last_failure_step and last_failure_code must be paired")
        if self.last_attempt_at is not None:
            _require_aware(self.last_attempt_at, "last_attempt_at")


@dataclass(frozen=True, slots=True)
class OrderSyncClaim:
    """One fencing-token lease returned by a successful claim transaction."""

    order_id: UUID
    claim_token: UUID
    claim_expires_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.order_id, "order_id")
        _require_uuid(self.claim_token, "claim_token")
        _require_aware(self.claim_expires_at, "claim_expires_at")


@dataclass(frozen=True, slots=True)
class OdooOrderReceipt:
    """Minimal durable Odoo receipt needed to resume later steps."""

    sale_order_id: int
    sale_order_name: str

    def __post_init__(self) -> None:
        if type(self.sale_order_id) is not int or self.sale_order_id <= 0:
            raise ValueError("sale_order_id must be a positive integer")
        _require_bounded(self.sale_order_name, "sale_order_name", _MAX_ODOO_ORDER_NAME_LENGTH)


@dataclass(frozen=True, slots=True)
class HubSpotCompanyReceipt:
    """Minimal durable HubSpot Company receipt."""

    company_id: str

    def __post_init__(self) -> None:
        _require_bounded(self.company_id, "company_id", _MAX_EXTERNAL_ID_LENGTH)


@dataclass(frozen=True, slots=True)
class HubSpotDealReceipt:
    """Minimal durable HubSpot Deal receipt."""

    deal_id: str

    def __post_init__(self) -> None:
        _require_bounded(self.deal_id, "deal_id", _MAX_EXTERNAL_ID_LENGTH)


@dataclass(frozen=True, slots=True)
class HubSpotAssociationReceipt:
    """Minimal durable confirmation of the one required Deal–Company relation."""

    confirmed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.confirmed_at, "confirmed_at")


@dataclass(frozen=True, slots=True)
class OrderSyncStepFailure:
    """One bounded executor failure without provider diagnostics."""

    code: OrderSyncFailureCode
    retry_after: timedelta | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, OrderSyncFailureCode):
            raise ValueError("code must be an OrderSyncFailureCode")
        if self.retry_after is not None and (
            not isinstance(self.retry_after, timedelta) or self.retry_after < timedelta(0)
        ):
            raise ValueError("retry_after must be a nonnegative timedelta or None")


type OrderSyncReceipt = (
    OdooOrderReceipt | HubSpotCompanyReceipt | HubSpotDealReceipt | HubSpotAssociationReceipt
)
type OrderSyncStepResult = OrderSyncReceipt | OrderSyncStepFailure | None


class OrderSyncStepExecutor(Protocol):
    """Provider-free application seam for one bounded step execution."""

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult: ...


@dataclass(frozen=True, slots=True)
class OrderSyncExecutionResult:
    """Bounded result returned by one execute-next invocation."""

    kind: ExecuteNextKind
    order_id: UUID | None
    state: OrderState | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExecuteNextKind):
            raise ValueError("kind must be an ExecuteNextKind")
        if self.order_id is not None:
            _require_uuid(self.order_id, "order_id")
        if self.state is not None and not isinstance(self.state, OrderState):
            raise ValueError("state must be an OrderState or None")
        if (self.order_id is None) != (self.state is None):
            raise ValueError("order_id and state must be both set or both empty")


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_bounded(value: object, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a nonblank string of at most {maximum} characters")
