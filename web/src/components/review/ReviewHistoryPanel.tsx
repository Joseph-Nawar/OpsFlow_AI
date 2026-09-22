import { useEffect, useState } from "react";

import type { AuditEvent, CanonicalJsonValue, ReviewApiClient, ReviewRevision } from "../../api/review";

interface ReviewHistoryPanelProps {
  api: Pick<ReviewApiClient, "getAudit">;
  orderId: string;
  revisions: ReviewRevision[];
}

const MAX_FORMATTED_VALUE_LENGTH = 240;

function formatCanonicalValue(value: CanonicalJsonValue): string {
  let formatted: string;
  if (value === null) {
    formatted = "None";
  } else if (typeof value === "string") {
    formatted = value;
  } else if (typeof value === "number" || typeof value === "boolean") {
    formatted = String(value);
  } else {
    try {
      formatted = JSON.stringify(value);
    } catch {
      formatted = "Structured value unavailable";
    }
  }
  return formatted.length > MAX_FORMATTED_VALUE_LENGTH
    ? `${formatted.slice(0, MAX_FORMATTED_VALUE_LENGTH)}…`
    : formatted;
}

interface AuditHistoryProps {
  api: Pick<ReviewApiClient, "getAudit">;
  orderId: string;
}

function AuditHistory({ api, orderId }: AuditHistoryProps) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadAudit() {
      setLoading(true);
      setError(false);
      try {
        const result = await api.getAudit(orderId);
        if (!cancelled) {
          setEvents(result);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setEvents(null);
          setError(true);
          setLoading(false);
        }
      }
    }

    void loadAudit();
    return () => {
      cancelled = true;
    };
  }, [api, orderId, reloadKey]);

  if (loading) {
    return <p role="status">Loading order audit history…</p>;
  }
  if (error || events === null) {
    return (
      <div className="review-error" role="alert">
        <p>Unable to load order audit history. Please try again.</p>
        <button onClick={() => setReloadKey((current) => current + 1)} type="button">Retry audit history</button>
      </div>
    );
  }
  if (events.length === 0) {
    return <p>No order audit events recorded.</p>;
  }
  return (
    <ol className="review-history-list">
      {events.map((event) => (
        <li key={event.id}>
          <strong>{event.eventType}</strong>
          <span>{event.occurredAt} · {event.actor}</span>
          <span>{event.description}</span>
        </li>
      ))}
    </ol>
  );
}

function ReviewHistoryPanel({ api, orderId, revisions }: ReviewHistoryPanelProps) {
  return (
    <section aria-labelledby="history-heading" className="review-panel">
      <h2 id="history-heading">Review history</h2>
      <section aria-labelledby="revision-heading">
        <h3 id="revision-heading">Human review revisions</h3>
        {revisions.length === 0 ? (
          <p>No human review revisions recorded.</p>
        ) : (
          <ol className="review-history-list">
            {revisions.map((revision) => (
              <li key={revision.id}>
                <h4>Revision {revision.revisionNumber} · {revision.id}</h4>
                <span>{revision.createdAt} · {revision.actor}</span>
                {revision.changes.length === 0 ? (
                  <p>No field changes recorded.</p>
                ) : (
                  <table className="review-table">
                    <thead><tr><th scope="col">Field</th><th scope="col">Previous value</th><th scope="col">New value</th></tr></thead>
                    <tbody>
                      {revision.changes.map((change, index) => (
                        <tr key={`${change.fieldPath}-${index}`}>
                          <th scope="row">{change.fieldPath}</th>
                          <td>{formatCanonicalValue(change.oldValue)}</td>
                          <td>{formatCanonicalValue(change.newValue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="audit-heading">
        <h3 id="audit-heading">Order audit history</h3>
        <AuditHistory api={api} orderId={orderId} />
      </section>
    </section>
  );
}

export default ReviewHistoryPanel;
