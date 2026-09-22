import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import type { CanonicalJsonValue, ReviewApiClient, ReviewDetail } from "../api/review";
import ReviewEvidencePanel from "../components/review/ReviewEvidencePanel";
import ReviewDraftForm from "../components/review/ReviewDraftForm";
import ReviewHistoryPanel from "../components/review/ReviewHistoryPanel";
import ReviewReferencePanel from "../components/review/ReviewReferencePanel";

interface ReviewDetailPageProps {
  api: Pick<ReviewApiClient, "getDetail" | "getReferenceData" | "getAudit" | "saveDraft">;
}

function formatCanonicalValue(value: CanonicalJsonValue): string {
  if (value === null) {
    return "None";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    const formatted = JSON.stringify(value);
    return formatted.length > 240 ? `${formatted.slice(0, 240)}…` : formatted;
  } catch {
    return "Structured value unavailable";
  }
}

function nullableText(value: string | null): string {
  return value ?? "Not provided";
}

function DraftSection({ draft }: { draft: ReviewDetail["effectiveDraft"] }) {
  return (
    <section aria-labelledby="effective-heading" className="review-panel">
      <h2 id="effective-heading">HUMAN-REVIEWED effective values (untrusted candidate)</h2>
      <p className="review-panel-note">These values remain untrusted until deterministic backend validation succeeds.</p>
      {draft === null ? (
        <p>No human-reviewed effective draft is available.</p>
      ) : (
        <>
          <dl className="review-data-list">
            <div><dt>Customer name</dt><dd>{nullableText(draft.customerName)}</dd></div>
            <div><dt>Customer reference</dt><dd>{nullableText(draft.customerReference)}</dd></div>
            <div><dt>PO number</dt><dd>{nullableText(draft.poNumber)}</dd></div>
            <div><dt>Order date</dt><dd>{nullableText(draft.orderDate)}</dd></div>
            <div><dt>Requested delivery date</dt><dd>{nullableText(draft.requestedDeliveryDate)}</dd></div>
            <div><dt>Currency</dt><dd>{nullableText(draft.currency)}</dd></div>
            <div><dt>Source snapshot ID</dt><dd>{nullableText(draft.sourceSnapshotId)}</dd></div>
            <div><dt>Latest revision number</dt><dd>{draft.latestRevisionNumber ?? "No revisions"}</dd></div>
          </dl>
          <h3>Candidate lines</h3>
          {draft.lines.length === 0 ? (
            <p>No candidate lines are available.</p>
          ) : (
            <table className="review-table">
              <thead><tr><th scope="col">SKU</th><th scope="col">Description</th><th scope="col">Quantity</th><th scope="col">Submitted price</th></tr></thead>
              <tbody>
                {draft.lines.map((line, index) => (
                  <tr key={`${line.sku ?? "line"}-${index}`}>
                    <td>{nullableText(line.sku)}</td>
                    <td>{nullableText(line.description)}</td>
                    <td>{nullableText(line.quantity)}</td>
                    <td>{nullableText(line.submittedPrice)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

function TrustedOrderSection({ detail }: { detail: ReviewDetail }) {
  return (
    <section aria-labelledby="trusted-heading" className="review-panel">
      <h2 id="trusted-heading">TRUSTED persisted order</h2>
      <p className="review-panel-note">These values are the current persisted Phase 1 order graph.</p>
      <dl className="review-data-list">
        <div><dt>Order ID</dt><dd>{detail.order.id}</dd></div>
        <div><dt>Customer reference</dt><dd>{nullableText(detail.order.customerReference)}</dd></div>
        <div><dt>PO number</dt><dd>{nullableText(detail.order.poNumber)}</dd></div>
        <div><dt>Order date</dt><dd>{nullableText(detail.order.orderDate)}</dd></div>
        <div><dt>Requested delivery date</dt><dd>{nullableText(detail.order.requestedDeliveryDate)}</dd></div>
        <div><dt>Currency</dt><dd>{nullableText(detail.order.currency)}</dd></div>
      </dl>
      <h3>Trusted order lines</h3>
      {detail.order.lines.length === 0 ? (
        <p>No trusted order lines are available.</p>
      ) : (
        <table className="review-table">
          <thead><tr><th scope="col">SKU</th><th scope="col">Description</th><th scope="col">Quantity</th><th scope="col">Submitted price</th><th scope="col">Trusted catalogue price</th></tr></thead>
          <tbody>
            {detail.order.lines.map((line) => (
              <tr key={line.id}>
                <td>{nullableText(line.sku)}</td>
                <td>{nullableText(line.description)}</td>
                <td>{line.quantity}</td>
                <td>{nullableText(line.submittedPrice)}</td>
                <td>{nullableText(line.trustedCataloguePrice)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ValidationIssuesSection({ detail }: { detail: ReviewDetail }) {
  return (
    <section aria-labelledby="validation-heading" className="review-panel">
      <h2 id="validation-heading">DETERMINISTIC validation results</h2>
      <p className="review-panel-note">These are backend-generated validation findings, not AI confidence claims.</p>
      {detail.validationIssues.length === 0 ? (
        <p>No deterministic validation issues are recorded.</p>
      ) : (
        <ul className="review-issue-list">
          {detail.validationIssues.map((issue, index) => (
            <li key={`${issue.ruleCode}-${index}`}>
              <h3>{issue.ruleCode}</h3>
              <dl className="review-data-list">
                <div><dt>Severity</dt><dd>{issue.severity}</dd></div>
                <div><dt>Field</dt><dd>{issue.field ?? "Not specified"}</dd></div>
                <div><dt>Expected</dt><dd>{formatCanonicalValue(issue.expected)}</dd></div>
                <div><dt>Actual</dt><dd>{formatCanonicalValue(issue.actual)}</dd></div>
                <div><dt>Explanation</dt><dd>{issue.explanation}</dd></div>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function OperatorSummary({ detail }: { detail: ReviewDetail }) {
  const { actions, operator } = detail;
  return (
    <section aria-labelledby="operator-heading" className="review-panel review-operator-panel">
      <h2 id="operator-heading">Server-resolved operator and action flags</h2>
      <p>Operator: {operator.actor} ({operator.role})</p>
      <p className="review-panel-note">Action flags are informational; the server remains authoritative.</p>
      <ul className="review-action-flags">
        <li>Can edit: {actions.canEdit ? "Yes" : "No"}</li>
        <li>Can approve: {actions.canApprove ? "Yes" : "No"}</li>
        <li>Can reject: {actions.canReject ? "Yes" : "No"}</li>
        <li>Can retry: {actions.canRetry ? "Yes" : "No"}</li>
      </ul>
    </section>
  );
}

function ReviewDetailPage({ api }: ReviewDetailPageProps) {
  const { orderId } = useParams();
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [revalidationMessage, setRevalidationMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(false);
      setRevalidationMessage(null);
      if (orderId === undefined) {
        setDetail(null);
        setError(true);
        setLoading(false);
        return;
      }
      try {
        const result = await api.getDetail(orderId);
        if (!cancelled) {
          setDetail(result);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setDetail(null);
          setError(true);
          setLoading(false);
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [api, orderId, reloadKey]);

  const reloadFromForm = useCallback(async () => {
    if (orderId === undefined) {
      return false;
    }
    try {
      const result = await api.getDetail(orderId);
      setDetail(result);
      setError(false);
      setRevalidationMessage(null);
      return true;
    } catch {
      setError(true);
      return false;
    }
  }, [api, orderId]);

  return (
    <main className="review-detail">
      <Link className="review-back-link" to="/review">Back to review queue</Link>
      {loading ? <p className="queue-status" role="status">Loading review case…</p> : null}
      {!loading && error ? (
        <section className="review-error" role="alert">
          <p>Unable to load this review case. Please try again.</p>
          <button onClick={() => setReloadKey((current) => current + 1)} type="button">Retry review case</button>
        </section>
      ) : null}
      {!loading && detail !== null && orderId !== undefined ? (
        <>
          <header className="review-detail-header">
            <p className="eyebrow">OpsFlow AI · Human review</p>
            <h1>Review case {orderId}</h1>
            <p className="review-state-label">State: {detail.order.state}</p>
          </header>
          {revalidationMessage !== null ? (
            <p className="review-form-success" role="status">{revalidationMessage}</p>
          ) : null}
          <OperatorSummary detail={detail} />
          <ReviewEvidencePanel
            originalExtraction={detail.originalExtraction}
            sourceDocuments={detail.sourceDocuments}
            sourceSnapshot={detail.sourceSnapshot}
          />
          <DraftSection draft={detail.effectiveDraft} />
          {detail.actions.canEdit && detail.effectiveDraft !== null ? (
            <ReviewDraftForm
              api={api}
              draft={detail.effectiveDraft}
              etag={detail.etag}
              key={detail.etag}
              onReload={reloadFromForm}
              onSaved={(savedDetail) => {
                setDetail(savedDetail);
                setError(false);
                setRevalidationMessage(
                  savedDetail.order.state === "NEEDS_REVIEW"
                    ? "Save & revalidate completed, but blocking deterministic issues remain."
                    : "Deterministic revalidation passed; the order is ready for approval.",
                );
              }}
              orderId={orderId}
            />
          ) : null}
          <TrustedOrderSection detail={detail} />
          <ValidationIssuesSection detail={detail} />
          <ReviewReferencePanel api={api} orderId={orderId} />
          <ReviewHistoryPanel api={api} orderId={orderId} revisions={detail.revisions} />
        </>
      ) : null}
    </main>
  );
}

export default ReviewDetailPage;
