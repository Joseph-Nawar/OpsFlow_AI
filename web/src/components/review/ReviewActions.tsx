import { useState, type FormEvent } from "react";

import { ReviewApiError } from "../../api/review";
import type { ReviewApiClient, ReviewCommandResult, ReviewDetail } from "../../api/review";

interface ReviewActionsProps {
  api: Pick<ReviewApiClient, "approve" | "reject" | "retry">;
  detail: ReviewDetail;
  onCommandCompleted: (result: ReviewCommandResult) => void;
  onReload: () => Promise<boolean>;
  orderId: string;
}

function safeCommandError(error: unknown): string {
  if (error instanceof ReviewApiError) {
    return error.message;
  }
  return "Unable to complete this review action. Please try again.";
}

function ReviewActions({ api, detail, onCommandCompleted, onReload, orderId }: ReviewActionsProps) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [stale, setStale] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const disabled = submitting || reloading || stale;
  const highValueApprovalRequired = detail.validationIssues.some(
    (issue) => issue.ruleCode === "HIGH_VALUE_APPROVAL_REQUIRED" && issue.severity === "WARNING",
  );
  const hasActions = detail.actions.canApprove || detail.actions.canReject || detail.actions.canRetry;

  if (!hasActions) {
    return null;
  }

  async function runCommand(command: () => Promise<ReviewCommandResult>) {
    if (disabled) {
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    try {
      const result = await command();
      onCommandCompleted(result);
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 412 && error.code === "PRECONDITION_FAILED") {
        setStale(true);
        setErrorMessage("This review case changed and must be reloaded.");
      } else {
        setErrorMessage(safeCommandError(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runCommand(() => api.reject(orderId, reason, detail.etag));
  }

  async function handleReload() {
    setReloading(true);
    try {
      const reloaded = await onReload();
      if (reloaded) {
        setStale(false);
        setErrorMessage(null);
      } else if (stale) {
        setErrorMessage("Unable to reload this review case. Please try again.");
      }
    } catch {
      setErrorMessage("Unable to reload this review case. Please try again.");
    } finally {
      setReloading(false);
    }
  }

  return (
    <section aria-labelledby="review-actions-heading" className="review-panel review-actions">
      <h2 id="review-actions-heading">Review actions</h2>
      {highValueApprovalRequired ? (
        <p className="review-panel-note">
          {detail.actions.canApprove
            ? "The server has permitted elevated approval for this high-value order."
            : "High-value approval is required; the server controls who may approve."}
        </p>
      ) : null}
      {detail.actions.canRetry ? (
        <p className="review-panel-note">
          Retry only restores the persisted failure origin; resumed processing is outside Phase 6.
        </p>
      ) : null}
      {errorMessage !== null ? (
        <div className="review-error" role="alert">
          <p>{errorMessage}</p>
          {stale ? (
            <button disabled={reloading} onClick={() => void handleReload()} type="button">
              {reloading ? "Reloading review case…" : "Reload review case"}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="review-actions-buttons">
        {detail.actions.canApprove ? (
          <button
            disabled={disabled}
            onClick={() => void runCommand(() => api.approve(orderId, detail.etag))}
            type="button"
          >
            {submitting ? "Approving…" : "Approve order"}
          </button>
        ) : null}
        {detail.actions.canRetry ? (
          <button
            disabled={disabled}
            onClick={() => void runCommand(() => api.retry(orderId, detail.etag))}
            type="button"
          >
            {submitting ? "Retrying…" : "Retry order"}
          </button>
        ) : null}
        {detail.actions.canReject ? (
          <form onSubmit={(event) => void handleReject(event)}>
            <label htmlFor="review-rejection-reason">Rejection reason</label>
            <textarea
              disabled={disabled}
              id="review-rejection-reason"
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              required
              value={reason}
            />
            <button disabled={disabled} type="submit">
              {submitting ? "Rejecting…" : "Reject order"}
            </button>
          </form>
        ) : null}
      </div>
    </section>
  );
}

export default ReviewActions;
