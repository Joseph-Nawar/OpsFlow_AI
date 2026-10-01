"""Application services for durable, fenced Phase 9 order synchronization."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Literal, overload
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent, Order, OrderState
from opsflow.order_sync.contracts import (
    ExecuteNextKind,
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OdooOrderReceipt,
    OrderSync,
    OrderSyncClaim,
    OrderSyncExecutionResult,
    OrderSyncFailureCode,
    OrderSyncReceipt,
    OrderSyncStep,
    OrderSyncStepExecutor,
    OrderSyncStepFailure,
)
from opsflow.persistence.mappers import order_sync_from_model
from opsflow.persistence.models import OrderModel, OrderSyncModel
from opsflow.persistence.order_sync_repository import (
    claim_one_eligible_order_sync,
    get_order_sync_claim_for_update,
    get_order_sync_state,
    insert_order_sync_intent,
    reset_order_sync_for_human_retry,
)
from opsflow.persistence.repositories import insert_audit_event, update_order_snapshot

_ACTOR = "opsflow-order-sync"
_monotonic = time.monotonic
_LEASE_INTERVAL = text("interval '5 minutes'")
_EXECUTION_BUDGET = timedelta(seconds=210)
_RECEIPT_TRANSACTION_ALLOWANCE = timedelta(seconds=5)
_STEP_TIMEOUTS = {
    OrderSyncStep.ODOO_LOOKUP: timedelta(seconds=20),
    OrderSyncStep.ODOO_BRIDGE: timedelta(seconds=20),
    OrderSyncStep.HUBSPOT_COMPANY: timedelta(seconds=15),
    OrderSyncStep.HUBSPOT_DEAL: timedelta(seconds=15),
    OrderSyncStep.HUBSPOT_ASSOCIATION: timedelta(seconds=15),
}
_AUTO_RETRY_CODES = {
    OrderSyncFailureCode.PROVIDER_UNAVAILABLE,
    OrderSyncFailureCode.PROVIDER_RATE_LIMIT,
    OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE,
    OrderSyncFailureCode.PROVIDER_PENDING,
}
_FINAL_FAILURE_CODES = {
    OrderSyncFailureCode.IDEMPOTENCY_CONFLICT,
    OrderSyncFailureCode.RECONCILIATION_REQUIRED,
}


class OrderSyncNotFoundError(Exception):
    """No durable synchronization intent exists for the requested order."""


class StaleOrderSyncClaimError(Exception):
    """The supplied token no longer owns an unexpired synchronization lease."""


class OrderSyncStepPreconditionError(Exception):
    """A step was requested before its required durable predecessor exists."""


class OrderSyncCompletionError(Exception):
    """The order cannot complete until every required receipt is durable."""


class OrderSyncExecutionDeadlineExceeded(Exception):
    """One bounded coordinator phase could not finish within the request budget."""


async def create_order_sync_intent(
    session: AsyncSession,
    order_id: UUID,
    created_at: datetime,
) -> None:
    """Create sync intent without committing the caller's approval transaction."""

    await insert_order_sync_intent(session, order_id, created_at)


async def reset_order_sync_for_retry(session: AsyncSession, order_id: UUID) -> bool:
    """Reset the sync retry generation within the caller's human Retry transaction."""

    return await reset_order_sync_for_human_retry(session, order_id)


@overload
async def claim_next_order_sync(session: AsyncSession) -> OrderSyncClaim | None: ...


@overload
async def claim_next_order_sync(
    session: AsyncSession, *, include_exhaustion_result: Literal[True]
) -> OrderSyncClaim | OrderSyncExecutionResult | None: ...


async def claim_next_order_sync(
    session: AsyncSession, *, include_exhaustion_result: bool = False
) -> OrderSyncClaim | OrderSyncExecutionResult | None:
    """Claim at most one eligible row and commit its five-minute fencing lease."""

    claim: OrderSyncClaim | None = None
    async with session.begin():
        selected = await claim_one_eligible_order_sync(session)
        if selected is None:
            return None
        sync_row, order_row = selected
        now = await session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("database clock did not return a timestamp")

        expired = (
            sync_row.claim_token is not None
            and sync_row.claim_expires_at is not None
            and sync_row.claim_expires_at <= now
        )
        if expired and not _has_all_receipts(sync_row):
            sync_row.attempt_count += 1
            if sync_row.attempt_count >= 3:
                failure_step = _step_from_model(sync_row.in_flight_step) or next_order_sync_step(
                    order_sync_from_model(sync_row)
                )
                if failure_step is None:
                    raise OrderSyncCompletionError
                sync_row.last_failure_step = failure_step.value
                sync_row.last_failure_code = OrderSyncFailureCode.WORKER_LEASE_EXHAUSTED.value
                sync_row.claim_token = None
                sync_row.claim_expires_at = None
                sync_row.updated_at = func.now()
                failed = _order_from_row(order_row).transition_to(OrderState.FAILED_RETRYABLE)
                await update_order_snapshot(session, failed)
                await _insert_sync_audit(
                    session,
                    order_row.id,
                    "ORDER_SYNC_FAILED",
                    "A synchronization worker lease expired; operator retry is required.",
                    now,
                )
                await session.flush()
                if include_exhaustion_result:
                    return OrderSyncExecutionResult(
                        ExecuteNextKind.NEEDS_REVIEW,
                        order_row.id,
                        OrderState.FAILED_RETRYABLE,
                    )
                return None

        first_claim = order_row.state == OrderState.APPROVED.value
        if first_claim:
            await update_order_snapshot(
                session, _order_from_row(order_row).transition_to(OrderState.SYNCING)
            )
            event_type = "ORDER_SYNC_STARTED"
            description = "Approved order synchronization was claimed."
        else:
            event_type = "ORDER_SYNC_RESUMED"
            description = "Order synchronization was claimed for safe recovery."

        token = uuid4()
        sync_row.claim_token = token
        sync_row.claim_expires_at = func.now() + _LEASE_INTERVAL
        sync_row.last_attempt_at = func.now()
        sync_row.updated_at = func.now()
        await _insert_sync_audit(session, order_row.id, event_type, description, now)
        await session.flush()
        await session.refresh(sync_row)
        assert sync_row.claim_expires_at is not None
        claim = OrderSyncClaim(order_row.id, token, sync_row.claim_expires_at)
    return claim


async def begin_order_sync_step(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
    step: OrderSyncStep,
) -> OrderSync:
    """Persist the bounded in-flight checkpoint before executor work begins."""

    async with session.begin():
        sync_row, _ = await _require_current_claim(session, order_id, claim_token)
        _require_step_preconditions(sync_row, step)
        current_step = _step_from_model(sync_row.in_flight_step)
        if (
            current_step is not None
            and current_step is not step
            and not (
                current_step is OrderSyncStep.ODOO_LOOKUP and step is OrderSyncStep.ODOO_BRIDGE
            )
        ):
            raise OrderSyncStepPreconditionError
        sync_row.in_flight_step = step.value
        sync_row.last_attempt_at = func.now()
        sync_row.updated_at = func.now()
        await session.flush()
        await session.refresh(sync_row)
        return order_sync_from_model(sync_row)


async def persist_order_sync_receipt(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
    receipt: OrderSyncReceipt,
) -> OrderSync:
    """Persist one confirmed provider receipt under the current live fence."""

    step = _receipt_step(receipt)
    async with session.begin():
        sync_row, _ = await _require_current_claim(session, order_id, claim_token)
        if sync_row.in_flight_step != step.value:
            raise OrderSyncStepPreconditionError
        _require_step_preconditions(sync_row, step)
        if isinstance(receipt, OdooOrderReceipt):
            sync_row.odoo_sale_order_id = receipt.sale_order_id
            sync_row.odoo_sale_order_name = receipt.sale_order_name
        elif isinstance(receipt, HubSpotCompanyReceipt):
            sync_row.hubspot_company_id = receipt.company_id
        elif isinstance(receipt, HubSpotDealReceipt):
            sync_row.hubspot_deal_id = receipt.deal_id
        else:
            sync_row.hubspot_association_confirmed_at = receipt.confirmed_at
        sync_row.in_flight_step = None
        sync_row.last_failure_step = None
        sync_row.last_failure_code = None
        sync_row.last_attempt_at = func.now()
        sync_row.updated_at = func.now()
        await session.flush()
        await session.refresh(sync_row)
        return order_sync_from_model(sync_row)


async def record_order_sync_failure(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
    step: OrderSyncStep,
    code: OrderSyncFailureCode,
    retry_after: timedelta | None = None,
) -> OrderSync:
    """Persist a bounded automatic, operator-action, or final failure."""

    if not isinstance(step, OrderSyncStep) or not isinstance(code, OrderSyncFailureCode):
        raise ValueError("step and code must use the bounded order-sync contracts")
    if retry_after is not None and (
        not isinstance(retry_after, timedelta) or retry_after < timedelta(0)
    ):
        raise ValueError("retry_after must be a nonnegative timedelta or None")

    async with session.begin():
        sync_row, order_row = await _require_current_claim(session, order_id, claim_token)
        if sync_row.in_flight_step != step.value:
            raise OrderSyncStepPreconditionError
        sync_row.last_failure_step = step.value
        sync_row.last_failure_code = code.value
        sync_row.claim_token = None
        sync_row.claim_expires_at = None
        sync_row.updated_at = func.now()
        current_order = _order_from_row(order_row)

        if code in _FINAL_FAILURE_CODES:
            failed = current_order.transition_to(OrderState.FAILED_FINAL)
            await update_order_snapshot(session, failed)
        elif code in _AUTO_RETRY_CODES:
            sync_row.attempt_count += 1
            if sync_row.attempt_count >= 3:
                failed = current_order.transition_to(OrderState.FAILED_RETRYABLE)
                await update_order_snapshot(session, failed)
                sync_row.next_attempt_at = func.now()
            else:
                base_delay = timedelta(seconds=30 if sync_row.attempt_count == 1 else 120)
                delay = max(base_delay, retry_after or timedelta(0))
                sync_row.next_attempt_at = func.now() + delay
        else:
            failed = current_order.transition_to(OrderState.FAILED_RETRYABLE)
            await update_order_snapshot(session, failed)
            sync_row.next_attempt_at = func.now()

        now = await session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("database clock did not return a timestamp")
        await _insert_sync_audit(
            session,
            order_id,
            "ORDER_SYNC_FAILED",
            "A bounded synchronization step failed; recovery is scheduled or requires review.",
            now,
        )
        await session.flush()
        await session.refresh(sync_row)
        return order_sync_from_model(sync_row)


async def yield_order_sync_claim(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
) -> OrderSync:
    """Release a live claim for a clean budget yield without spending an attempt."""

    async with session.begin():
        sync_row, _ = await _require_current_claim(session, order_id, claim_token)
        sync_row.claim_token = None
        sync_row.claim_expires_at = None
        sync_row.next_attempt_at = func.now()
        sync_row.updated_at = func.now()
        await session.flush()
        await session.refresh(sync_row)
        return order_sync_from_model(sync_row)


async def complete_order_sync(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
) -> OrderSync:
    """Complete only after all four external receipts are durably present."""

    async with session.begin():
        sync_row, order_row = await _require_current_claim(session, order_id, claim_token)
        if not _has_all_receipts(sync_row):
            raise OrderSyncCompletionError
        order = _order_from_row(order_row)
        if order.state is not OrderState.SYNCING:
            raise OrderSyncCompletionError
        completed = order.transition_to(OrderState.COMPLETED)
        await update_order_snapshot(session, completed)
        sync_row.claim_token = None
        sync_row.claim_expires_at = None
        sync_row.updated_at = func.now()
        now = await session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("database clock did not return a timestamp")
        await _insert_sync_audit(
            session,
            order_id,
            "ORDER_SYNC_COMPLETED",
            "All required ERP and CRM synchronization receipts are durable.",
            now,
        )
        await session.flush()
        await session.refresh(sync_row)
        completed_sync = order_sync_from_model(sync_row)
    return completed_sync


async def execute_next_order_sync(
    session: AsyncSession,
    executor: OrderSyncStepExecutor,
    *,
    execution_budget: timedelta = _EXECUTION_BUDGET,
) -> OrderSyncExecutionResult:
    """Claim and execute one safe progression, checkpointing every provider step."""

    if executor is None:
        raise ValueError("an order-sync executor is required")
    if not isinstance(execution_budget, timedelta) or execution_budget < timedelta(0):
        raise ValueError("execution_budget must be a nonnegative timedelta")
    deadline = _monotonic() + execution_budget.total_seconds()
    cleanup_allowance = min(
        _RECEIPT_TRANSACTION_ALLOWANCE.total_seconds(),
        execution_budget.total_seconds() / 10,
    )
    claim_or_result = await _within_deadline(
        lambda: claim_next_order_sync(session, include_exhaustion_result=True),
        deadline,
        reserve=cleanup_allowance,
    )
    if isinstance(claim_or_result, OrderSyncExecutionResult):
        return claim_or_result
    claim = claim_or_result
    if claim is None:
        return OrderSyncExecutionResult(ExecuteNextKind.NO_WORK, None, None)

    lookup_succeeded = False
    try:
        sync_row = await _within_deadline(
            lambda: _get_order_sync(session, claim.order_id),
            deadline,
            reserve=cleanup_allowance,
        )
    except OrderSyncExecutionDeadlineExceeded:
        return await _yield_for_budget(session, claim, deadline)

    while True:
        step = next_order_sync_step(sync_row, lookup_succeeded=lookup_succeeded)
        if step is None:
            try:
                await _within_deadline(
                    lambda: complete_order_sync(session, claim.order_id, claim.claim_token),
                    deadline,
                )
                return OrderSyncExecutionResult(
                    ExecuteNextKind.COMPLETED, claim.order_id, OrderState.COMPLETED
                )
            except StaleOrderSyncClaimError:
                return await _stale_claim_result(session, claim.order_id, deadline)

        remaining = deadline - _monotonic()
        required = _STEP_TIMEOUTS[step] + _RECEIPT_TRANSACTION_ALLOWANCE
        if remaining < required.total_seconds():
            return await _yield_for_budget(session, claim, deadline)

        try:
            await _within_deadline(
                partial(begin_order_sync_step, session, claim.order_id, claim.claim_token, step),
                deadline,
                reserve=required.total_seconds(),
            )
        except StaleOrderSyncClaimError:
            return await _stale_claim_result(session, claim.order_id, deadline)
        except OrderSyncExecutionDeadlineExceeded:
            return await _yield_for_budget(session, claim, deadline)
        provider_timeout = min(
            _STEP_TIMEOUTS[step].total_seconds(),
            deadline - _monotonic() - _RECEIPT_TRANSACTION_ALLOWANCE.total_seconds(),
        )
        if provider_timeout <= 0:
            return await _yield_for_budget(session, claim, deadline)
        try:
            async with asyncio.timeout(provider_timeout):
                outcome = await executor.execute(claim.order_id, step)
        except TimeoutError:
            outcome = OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        except Exception:
            outcome = OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)

        if isinstance(outcome, OrderSyncStepFailure):
            try:
                updated = await _within_deadline(
                    partial(
                        record_order_sync_failure,
                        session,
                        claim.order_id,
                        claim.claim_token,
                        step,
                        outcome.code,
                        outcome.retry_after,
                    ),
                    deadline,
                )
            except StaleOrderSyncClaimError:
                return await _stale_claim_result(session, claim.order_id, deadline)
            return await _failure_result(session, claim.order_id, updated, deadline)
        receipt = outcome

        if step is OrderSyncStep.ODOO_LOOKUP:
            if receipt is not None:
                try:
                    updated = await _within_deadline(
                        partial(
                            record_order_sync_failure,
                            session,
                            claim.order_id,
                            claim.claim_token,
                            step,
                            OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE,
                        ),
                        deadline,
                    )
                except StaleOrderSyncClaimError:
                    return await _stale_claim_result(session, claim.order_id, deadline)
                return await _failure_result(session, claim.order_id, updated, deadline)
            lookup_succeeded = True
            continue

        actual_receipt_step = (
            _receipt_step(receipt)
            if isinstance(
                receipt,
                (
                    OdooOrderReceipt,
                    HubSpotCompanyReceipt,
                    HubSpotDealReceipt,
                    HubSpotAssociationReceipt,
                ),
            )
            else None
        )
        if receipt is None or actual_receipt_step is not step:
            try:
                updated = await _within_deadline(
                    partial(
                        record_order_sync_failure,
                        session,
                        claim.order_id,
                        claim.claim_token,
                        step,
                        OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE,
                    ),
                    deadline,
                )
            except StaleOrderSyncClaimError:
                return await _stale_claim_result(session, claim.order_id, deadline)
            return await _failure_result(session, claim.order_id, updated, deadline)

        try:
            sync_row = await _within_deadline(
                partial(
                    persist_order_sync_receipt,
                    session,
                    claim.order_id,
                    claim.claim_token,
                    receipt,
                ),
                deadline,
            )
        except StaleOrderSyncClaimError:
            current_state = await _within_deadline(
                lambda: _read_order_state(session, claim.order_id), deadline
            )
            return OrderSyncExecutionResult(
                ExecuteNextKind.RETRY_WAIT, claim.order_id, current_state
            )
        except IntegrityError as error:
            if not _is_external_receipt_collision(error):
                raise
            try:
                updated = await _within_deadline(
                    partial(
                        record_order_sync_failure,
                        session,
                        claim.order_id,
                        claim.claim_token,
                        step,
                        OrderSyncFailureCode.IDEMPOTENCY_CONFLICT,
                    ),
                    deadline,
                )
            except StaleOrderSyncClaimError:
                return await _stale_claim_result(session, claim.order_id, deadline)
            return await _failure_result(session, claim.order_id, updated, deadline)
        lookup_succeeded = False


async def _require_current_claim(
    session: AsyncSession,
    order_id: UUID,
    claim_token: UUID,
) -> tuple[OrderSyncModel, OrderModel]:
    selected = await get_order_sync_claim_for_update(session, order_id)
    if selected is None:
        raise OrderSyncNotFoundError
    sync_row, order_row = selected
    # `now()` is fixed at transaction start and can incorrectly preserve a lease
    # while this transaction waits for the order/sync row locks above.
    now = await session.scalar(select(func.clock_timestamp()))
    if (
        now is None
        or order_row.state != OrderState.SYNCING.value
        or sync_row.claim_token != claim_token
        or sync_row.claim_expires_at is None
        or sync_row.claim_expires_at <= now
    ):
        raise StaleOrderSyncClaimError
    return sync_row, order_row


async def _get_order_sync(session: AsyncSession, order_id: UUID) -> OrderSync:
    async with session.begin():
        row = await session.get(OrderSyncModel, order_id)
        if row is None:
            raise OrderSyncNotFoundError
        return order_sync_from_model(row)


async def _within_deadline[T](
    operation: Callable[[], Awaitable[T]],
    deadline: float,
    *,
    reserve: float = 0,
) -> T:
    """Bound one coordinator phase by the request's absolute monotonic deadline."""

    remaining = deadline - _monotonic() - reserve
    if remaining <= 0:
        raise OrderSyncExecutionDeadlineExceeded
    try:
        async with asyncio.timeout(remaining):
            return await operation()
    except TimeoutError as error:
        raise OrderSyncExecutionDeadlineExceeded from error


async def _yield_for_budget(
    session: AsyncSession,
    claim: OrderSyncClaim,
    deadline: float,
) -> OrderSyncExecutionResult:
    try:
        await _within_deadline(
            lambda: yield_order_sync_claim(session, claim.order_id, claim.claim_token),
            deadline,
        )
    except StaleOrderSyncClaimError:
        return await _stale_claim_result(session, claim.order_id, deadline)
    return OrderSyncExecutionResult(ExecuteNextKind.YIELDED, claim.order_id, OrderState.SYNCING)


async def _failure_result(
    session: AsyncSession,
    order_id: UUID,
    sync: OrderSync,
    deadline: float,
) -> OrderSyncExecutionResult:
    state = await _within_deadline(lambda: _read_order_state(session, order_id), deadline)
    kind = (
        ExecuteNextKind.NEEDS_REVIEW
        if state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
        else ExecuteNextKind.RETRY_WAIT
    )
    return OrderSyncExecutionResult(kind, order_id, state)


async def _stale_claim_result(
    session: AsyncSession, order_id: UUID, deadline: float
) -> OrderSyncExecutionResult:
    """Return only the current bounded state after a fenced write is rejected."""

    state = await _within_deadline(lambda: _read_order_state(session, order_id), deadline)
    if state is None:
        return OrderSyncExecutionResult(ExecuteNextKind.NO_WORK, None, None)
    if state is OrderState.COMPLETED:
        kind = ExecuteNextKind.COMPLETED
    elif state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL):
        kind = ExecuteNextKind.NEEDS_REVIEW
    else:
        kind = ExecuteNextKind.RETRY_WAIT
    return OrderSyncExecutionResult(kind, order_id, state)


async def _read_order_state(session: AsyncSession, order_id: UUID) -> OrderState | None:
    async with session.begin():
        raw_state = await get_order_sync_state(session, order_id)
    if raw_state is None:
        return None
    return OrderState(raw_state)


def _order_from_row(row: OrderModel) -> Order:
    return Order(
        id=row.id,
        customer_reference=row.customer_reference,
        po_number=row.po_number,
        order_date=row.order_date,
        requested_delivery_date=row.requested_delivery_date,
        currency=row.currency,
        state=OrderState(row.state),
        failure_origin=OrderState(row.failure_origin) if row.failure_origin else None,
    )


def _step_from_model(raw: str | None) -> OrderSyncStep | None:
    return OrderSyncStep(raw) if raw is not None else None


def _receipt_step(receipt: OrderSyncReceipt) -> OrderSyncStep:
    if isinstance(receipt, OdooOrderReceipt):
        return OrderSyncStep.ODOO_BRIDGE
    if isinstance(receipt, HubSpotCompanyReceipt):
        return OrderSyncStep.HUBSPOT_COMPANY
    if isinstance(receipt, HubSpotDealReceipt):
        return OrderSyncStep.HUBSPOT_DEAL
    if isinstance(receipt, HubSpotAssociationReceipt):
        return OrderSyncStep.HUBSPOT_ASSOCIATION
    raise OrderSyncStepPreconditionError


def _require_step_preconditions(sync_row: OrderSyncModel, step: OrderSyncStep) -> None:
    if step is OrderSyncStep.ODOO_LOOKUP or step is OrderSyncStep.ODOO_BRIDGE:
        if sync_row.odoo_sale_order_id is not None:
            raise OrderSyncStepPreconditionError
    elif step is OrderSyncStep.HUBSPOT_COMPANY:
        if sync_row.odoo_sale_order_id is None:
            raise OrderSyncStepPreconditionError
    elif step is OrderSyncStep.HUBSPOT_DEAL:
        if sync_row.hubspot_company_id is None:
            raise OrderSyncStepPreconditionError
    elif step is OrderSyncStep.HUBSPOT_ASSOCIATION:
        if sync_row.hubspot_company_id is None or sync_row.hubspot_deal_id is None:
            raise OrderSyncStepPreconditionError
    else:
        raise OrderSyncStepPreconditionError


def next_order_sync_step(
    sync: OrderSync, *, lookup_succeeded: bool = False
) -> OrderSyncStep | None:
    """Return the first missing durable step, resuming an uncertain checkpoint."""

    if sync.odoo_sale_order_id is None:
        if sync.in_flight_step is OrderSyncStep.ODOO_BRIDGE or lookup_succeeded:
            return OrderSyncStep.ODOO_BRIDGE
        return OrderSyncStep.ODOO_LOOKUP
    if sync.hubspot_company_id is None:
        return OrderSyncStep.HUBSPOT_COMPANY
    if sync.hubspot_deal_id is None:
        return OrderSyncStep.HUBSPOT_DEAL
    if sync.hubspot_association_confirmed_at is None:
        return OrderSyncStep.HUBSPOT_ASSOCIATION
    return None


def _has_all_receipts(row: OrderSyncModel) -> bool:
    return all(
        value is not None
        for value in (
            row.odoo_sale_order_id,
            row.odoo_sale_order_name,
            row.hubspot_company_id,
            row.hubspot_deal_id,
            row.hubspot_association_confirmed_at,
        )
    )


def _is_external_receipt_collision(error: IntegrityError) -> bool:
    constraint_name = getattr(error.orig, "constraint_name", None) or getattr(
        getattr(error.orig, "diag", None), "constraint_name", None
    )
    return constraint_name in {
        "uq_order_syncs_odoo_sale_order_id",
        "uq_order_syncs_hubspot_deal_id",
    }


async def _insert_sync_audit(
    session: AsyncSession,
    order_id: UUID,
    event_type: str,
    description: str,
    occurred_at: datetime,
) -> None:
    await insert_audit_event(
        session,
        AuditEvent(
            id=uuid4(),
            order_id=order_id,
            event_type=event_type,
            actor=_ACTOR,
            occurred_at=occurred_at,
            description=description,
        ),
    )
