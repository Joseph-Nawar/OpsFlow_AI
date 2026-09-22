import { useEffect, useState } from "react";

import type { ReferenceData, ReviewApiClient } from "../../api/review";

interface ReviewReferencePanelProps {
  api: Pick<ReviewApiClient, "getReferenceData">;
  orderId: string;
}

function ReviewReferencePanel({ api, orderId }: ReviewReferencePanelProps) {
  const [data, setData] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadReferenceData() {
      setLoading(true);
      setError(false);
      try {
        const result = await api.getReferenceData(orderId);
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setData(null);
          setError(true);
          setLoading(false);
        }
      }
    }

    void loadReferenceData();
    return () => {
      cancelled = true;
    };
  }, [api, orderId, reloadKey]);

  if (loading) {
    return <section aria-labelledby="reference-heading" className="review-panel"><h2 id="reference-heading">Current trusted reference data</h2><p role="status">Loading current trusted reference data…</p></section>;
  }

  if (error || data === null) {
    return (
      <section aria-labelledby="reference-heading" className="review-panel">
        <h2 id="reference-heading">Current trusted reference data</h2>
        <div className="review-error" role="alert">
          <p>Current trusted reference data is unavailable. Please try again.</p>
          <button onClick={() => setReloadKey((current) => current + 1)} type="button">Retry reference data</button>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="reference-heading" className="review-panel">
      <h2 id="reference-heading">{data.label}</h2>
      <p className="review-panel-note">This is volatile current reference information, not persisted order truth.</p>

      <h3>Customer candidates</h3>
      {data.customerCandidates.length === 0 ? (
        <p>No customer candidates returned.</p>
      ) : (
        <ul className="review-reference-list">
          {data.customerCandidates.map((customer) => (
            <li key={customer.reference}>
              {customer.reference} — {customer.name} ({customer.active ? "active" : "inactive"})
            </li>
          ))}
        </ul>
      )}

      <h3>Products by ordered line</h3>
      {data.productsByLine.length === 0 ? (
        <p>No product reference results returned.</p>
      ) : (
        <ol className="review-reference-list">
          {data.productsByLine.map((product, index) => (
            <li key={`${product?.sku ?? "missing"}-${index}`}>
              {product === null ? (
                `Line ${index + 1}: No exact trusted product found.`
              ) : (
                <>
                  {product.sku} — {product.description ?? "No description"} ({product.active ? "active" : "inactive"})
                  <span className="review-reference-detail">
                    Currency: {product.currency}; Catalogue price: {product.cataloguePrice ?? "Not provided"}; Available quantity: {product.availableQuantity ?? "Not provided"}
                  </span>
                </>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export default ReviewReferencePanel;
