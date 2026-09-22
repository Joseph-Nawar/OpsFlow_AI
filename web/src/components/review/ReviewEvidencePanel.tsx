import type { OriginalExtraction, SourceDocument, SourceSnapshot } from "../../api/review";

interface ReviewEvidencePanelProps {
  sourceDocuments: SourceDocument[];
  sourceSnapshot: SourceSnapshot | null;
  originalExtraction: OriginalExtraction | null;
}

function nullableText(value: string | null): string {
  return value ?? "Not provided";
}

function ReviewEvidencePanel({
  sourceDocuments,
  sourceSnapshot,
  originalExtraction,
}: ReviewEvidencePanelProps) {
  return (
    <section aria-labelledby="evidence-heading" className="review-panel review-evidence-panel">
      <h2 id="evidence-heading">ORIGINAL AI extraction / provenance</h2>
      <p className="review-panel-note">
        This is the immutable AI interpretation and its provenance. Evidence does not prove a later human edit.
      </p>
      <p className="review-panel-note">Raw source files are not persisted or viewable in Phase 6.</p>

      <section aria-labelledby="source-documents-heading">
        <h3 id="source-documents-heading">Source documents</h3>
        {sourceDocuments.length === 0 ? (
          <p>No source documents are available.</p>
        ) : (
          <div className="review-card-list">
            {sourceDocuments.map((document) => (
              <article className="review-subcard" key={document.id}>
                <h4>{document.name}</h4>
                <dl className="review-data-list">
                  <div><dt>Document type</dt><dd>{document.documentType}</dd></div>
                  <div><dt>MIME type</dt><dd>{document.mimeType}</dd></div>
                  <div><dt>SHA-256</dt><dd className="review-breakable">{document.sha256}</dd></div>
                  <div><dt>Message reference</dt><dd>{nullableText(document.messageId)}</dd></div>
                  <div><dt>Storage/source reference</dt><dd>{nullableText(document.storageReference)}</dd></div>
                </dl>
                {document.metadata.length === 0 ? (
                  <p>No metadata pairs are available.</p>
                ) : (
                  <ul aria-label="Source metadata" className="review-metadata-list">
                    {document.metadata.map((pair, index) => (
                      <li key={`${pair.key}-${index}`}>{pair.key}: {pair.value}</li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="source-snapshot-heading">
        <h3 id="source-snapshot-heading">Immutable source snapshot</h3>
        {sourceSnapshot === null ? (
          <p>No source snapshot is available.</p>
        ) : (
          <dl className="review-data-list">
            <div><dt>Snapshot ID</dt><dd>{sourceSnapshot.id}</dd></div>
            <div><dt>Source document ID</dt><dd>{sourceSnapshot.sourceDocumentId}</dd></div>
            <div><dt>Source SHA-256</dt><dd className="review-breakable">{sourceSnapshot.sourceSha256}</dd></div>
            <div><dt>Source document type</dt><dd>{sourceSnapshot.sourceDocumentType}</dd></div>
            <div><dt>Created at</dt><dd>{sourceSnapshot.createdAt}</dd></div>
          </dl>
        )}
      </section>

      <section aria-labelledby="original-extraction-heading">
        <h3 id="original-extraction-heading">Original extraction values</h3>
        {originalExtraction === null ? (
          <p>No original AI extraction is available for this review case.</p>
        ) : (
          <>
            <dl className="review-data-list">
              <div><dt>Customer name</dt><dd>{nullableText(originalExtraction.customerName)}</dd></div>
              <div><dt>Customer reference</dt><dd>{nullableText(originalExtraction.customerReference)}</dd></div>
              <div><dt>PO number</dt><dd>{nullableText(originalExtraction.poNumber)}</dd></div>
              <div><dt>Order date</dt><dd>{nullableText(originalExtraction.orderDate)}</dd></div>
              <div><dt>Requested delivery date</dt><dd>{nullableText(originalExtraction.requestedDeliveryDate)}</dd></div>
              <div><dt>Currency</dt><dd>{nullableText(originalExtraction.currency)}</dd></div>
              <div><dt>Notes</dt><dd>{nullableText(originalExtraction.notes)}</dd></div>
            </dl>

            <h4>Extracted lines</h4>
            {originalExtraction.lines.length === 0 ? (
              <p>No extracted lines are available.</p>
            ) : (
              <table className="review-table">
                <thead><tr><th scope="col">SKU</th><th scope="col">Description</th><th scope="col">Quantity</th><th scope="col">Submitted price</th></tr></thead>
                <tbody>
                  {originalExtraction.lines.map((line, index) => (
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

            <h4>Original extraction evidence</h4>
            {originalExtraction.evidence.length === 0 ? (
              <p>No extraction evidence is available.</p>
            ) : (
              <ul className="review-evidence-list">
                {originalExtraction.evidence.map((item, index) => (
                  <li key={`${item.fieldPath}-${index}`}>
                    <strong>{item.fieldPath}</strong>
                    <dl className="review-data-list">
                      <div><dt>Source location</dt><dd>{item.sourceLocation ?? "No source location provided"}</dd></div>
                      <div><dt>Quote</dt><dd>{item.quote ?? "No quote provided"}</dd></div>
                    </dl>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </section>
  );
}

export default ReviewEvidencePanel;
