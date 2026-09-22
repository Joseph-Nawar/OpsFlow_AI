import { useEffect, useState } from "react";
import { Link } from "react-router";

import type {
  ReviewApiClient,
  ReviewQueueItem,
  ReviewQueuePage as ReviewQueuePageModel,
  ReviewState,
} from "../api/review";

const QUEUE_STATES: readonly ReviewState[] = [
  "NEEDS_REVIEW",
  "READY_FOR_APPROVAL",
  "FAILED_RETRYABLE",
];
const PAGE_SIZE = 50;
const KNOWN_QUEUE_STATES = new Set<string>(QUEUE_STATES);

interface ReviewQueuePageProps {
  api: Pick<ReviewApiClient, "listOrders">;
}

function displayState(state: unknown): string {
  return typeof state === "string" && KNOWN_QUEUE_STATES.has(state)
    ? state
    : "Unknown state";
}

function issueSummary(count: number): string {
  if (count === 0) {
    return "No validation issues";
  }
  return `${count} validation issue${count === 1 ? "" : "s"}`;
}

function QueueRow({ item }: { item: ReviewQueueItem }) {
  const safeState = displayState(item.state);
  const hasKnownState = safeState !== "Unknown state";
  const dateLabel = item.orderDate === null
    ? `Created: ${item.createdAt}`
    : `Order date: ${item.orderDate}`;

  return (
    <tr>
      <th scope="row">
        <Link className="queue-order-link" to={`/review/${encodeURIComponent(item.id)}`}>
          Open {item.id}
        </Link>
      </th>
      <td>
        <span className={hasKnownState ? "queue-state" : "queue-state queue-state-unknown"}>
          {safeState}
        </span>
      </td>
      <td>{item.customerReference ?? "Unknown customer"}</td>
      <td>{item.poNumber ?? "No PO number"}</td>
      <td>{dateLabel}</td>
      <td>{issueSummary(item.validationIssueCount)}</td>
      <td>
        {item.highValueApprovalRequired ? (
          <span className="queue-warning">High-value approval required</span>
        ) : (
          <span className="queue-muted">None</span>
        )}
      </td>
    </tr>
  );
}

function ReviewQueuePage({ api }: ReviewQueuePageProps) {
  const [selectedStates, setSelectedStates] = useState<ReviewState[]>([...QUEUE_STATES]);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ReviewQueuePageModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadQueue() {
      setLoading(true);
      setError(false);
      try {
        const result = await api.listOrders({
          states: selectedStates,
          limit: PAGE_SIZE,
          offset,
        });
        if (!cancelled) {
          setPage(result);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setPage(null);
          setError(true);
          setLoading(false);
        }
      }
    }

    void loadQueue();
    return () => {
      cancelled = true;
    };
  }, [api, offset, reloadKey, selectedStates]);

  function toggleState(state: ReviewState) {
    if (selectedStates.length === 1 && selectedStates[0] === state) {
      return;
    }

    setPage(null);
    setOffset(0);
    setSelectedStates((current) => current.includes(state)
      ? current.filter((candidate) => candidate !== state)
      : QUEUE_STATES.filter((candidate) => current.includes(candidate) || candidate === state));
  }

  function retryLoad() {
    setReloadKey((current) => current + 1);
  }

  const pageSize = page !== null && page.limit > 0 ? page.limit : PAGE_SIZE;
  const canPrevious = offset > 0;
  const canNext = page !== null && offset + pageSize < page.total;

  return (
    <main className="review-queue">
      <header className="review-page-header">
        <p className="eyebrow">OpsFlow AI · Human review</p>
        <h1>Review queue</h1>
        <p className="review-page-copy">
          Review orders that need deterministic validation or operator approval.
        </p>
      </header>

      <fieldset className="queue-filters">
        <legend>Queue states</legend>
        <div className="queue-filter-options">
          {QUEUE_STATES.map((state) => (
            <label key={state}>
              <input
                checked={selectedStates.includes(state)}
                disabled={selectedStates.length === 1 && selectedStates[0] === state}
                name="queue-state"
                onChange={() => toggleState(state)}
                type="checkbox"
              />
              {state}
            </label>
          ))}
        </div>
      </fieldset>

      {loading ? <p className="queue-status" role="status">Loading review queue…</p> : null}

      {!loading && error ? (
        <section className="queue-message" role="alert">
          <p>Unable to load the review queue. Please try again.</p>
          <button onClick={retryLoad} type="button">Retry</button>
        </section>
      ) : null}

      {!loading && !error && page !== null ? (
        <>
          {page.items.length === 0 ? (
            <p className="queue-message">No review orders match the selected states.</p>
          ) : (
            <div className="queue-table-wrapper">
              <table className="queue-table">
                <caption>Orders in the selected review queues</caption>
                <thead>
                  <tr>
                    <th scope="col">Order</th>
                    <th scope="col">State</th>
                    <th scope="col">Customer</th>
                    <th scope="col">PO number</th>
                    <th scope="col">Date</th>
                    <th scope="col">Validation</th>
                    <th scope="col">Approval warning</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((item) => <QueueRow item={item} key={item.id} />)}
                </tbody>
              </table>
            </div>
          )}

          <nav aria-label="Review queue pagination" className="queue-pagination">
            <button
              disabled={!canPrevious || loading}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              type="button"
            >
              Previous page
            </button>
            <span>
              Showing {page.total === 0 ? 0 : offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}
            </span>
            <button
              disabled={!canNext || loading}
              onClick={() => setOffset(offset + pageSize)}
              type="button"
            >
              Next page
            </button>
          </nav>
        </>
      ) : null}
    </main>
  );
}

export default ReviewQueuePage;
