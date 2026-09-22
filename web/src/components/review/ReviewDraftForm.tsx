import { useState, type FormEvent } from "react";

import { ReviewApiError } from "../../api/review";
import type { ReviewApiClient, ReviewDetail, ReviewDraft, ReviewLine } from "../../api/review";

interface ReviewDraftFormProps {
  api: Pick<ReviewApiClient, "saveDraft">;
  draft: ReviewDraft;
  etag: string;
  onReload: () => Promise<boolean>;
  onSaved: (detail: ReviewDetail) => void;
  orderId: string;
}

type DraftScalarField = Exclude<keyof ReviewDraft, "lines">;
type LineField = keyof ReviewLine;

const emptyLine: ReviewLine = {
  sku: null,
  description: null,
  quantity: null,
  submittedPrice: null,
};

function cloneDraft(draft: ReviewDraft): ReviewDraft {
  return {
    ...draft,
    lines: draft.lines.map((line) => ({ ...line })),
  };
}

function inputValue(value: string | null): string {
  return value ?? "";
}

function nullableValue(value: string): string | null {
  return value === "" ? null : value;
}

function ReviewDraftForm({ api, draft, etag, onReload, onSaved, orderId }: ReviewDraftFormProps) {
  const [candidate, setCandidate] = useState<ReviewDraft>(() => cloneDraft(draft));
  const [submitting, setSubmitting] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  function updateScalar(field: DraftScalarField, value: string) {
    setCandidate((current) => ({ ...current, [field]: nullableValue(value) }));
    setErrorMessage(null);
  }

  function updateLine(index: number, field: LineField, value: string) {
    setCandidate((current) => ({
      ...current,
      lines: current.lines.map((line, lineIndex) => (
        lineIndex === index ? { ...line, [field]: nullableValue(value) } : line
      )),
    }));
    setErrorMessage(null);
  }

  function addLine() {
    setCandidate((current) => ({ ...current, lines: [...current.lines, { ...emptyLine }] }));
    setErrorMessage(null);
  }

  function removeLine(index: number) {
    setCandidate((current) => ({
      ...current,
      lines: current.lines.filter((_, lineIndex) => lineIndex !== index),
    }));
    setErrorMessage(null);
  }

  function moveLine(index: number, direction: -1 | 1) {
    setCandidate((current) => {
      const destination = index + direction;
      if (destination < 0 || destination >= current.lines.length) {
        return current;
      }
      const lines = [...current.lines];
      [lines[index], lines[destination]] = [lines[destination], lines[index]];
      return { ...current, lines };
    });
    setErrorMessage(null);
  }

  async function handleReload() {
    setReloading(true);
    try {
      const reloaded = await onReload();
      if (reloaded) {
        setStale(false);
        setErrorMessage(null);
      }
    } catch {
      setErrorMessage("Unable to reload this review case. Please try again.");
    } finally {
      setReloading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || reloading) {
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setStale(false);

    try {
      const result = await api.saveDraft(orderId, cloneDraft(candidate), etag);
      onSaved(result);
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 409 && error.code === "NO_REVIEW_CHANGES") {
        setErrorMessage("No review changes were submitted.");
      } else if (error instanceof ReviewApiError && error.status === 412 && error.code === "PRECONDITION_FAILED") {
        setStale(true);
        setErrorMessage("This review case changed and must be reloaded.");
      } else if (error instanceof ReviewApiError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("Unable to save and revalidate this review case. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="draft-form-heading" className="review-panel review-draft-form-panel">
      <h2 id="draft-form-heading">Correct untrusted review draft</h2>
      <p className="review-panel-note">
        Edit only the untrusted candidate values below. The backend will validate and decide whether trusted order data changes.
      </p>
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
      <form aria-busy={submitting || reloading} onSubmit={(event) => void handleSubmit(event)}>
        <fieldset disabled={submitting || reloading}>
          <legend>Editable order values</legend>
          <div className="review-form-grid">
            <label htmlFor="review-customer-name">Customer name</label>
            <input
              id="review-customer-name"
              onChange={(event) => updateScalar("customerName", event.target.value)}
              type="text"
              value={inputValue(candidate.customerName)}
            />

            <label htmlFor="review-customer-reference">Customer reference</label>
            <input
              id="review-customer-reference"
              onChange={(event) => updateScalar("customerReference", event.target.value)}
              type="text"
              value={inputValue(candidate.customerReference)}
            />

            <label htmlFor="review-po-number">PO number</label>
            <input
              id="review-po-number"
              onChange={(event) => updateScalar("poNumber", event.target.value)}
              type="text"
              value={inputValue(candidate.poNumber)}
            />

            <label htmlFor="review-order-date">Order date</label>
            <input
              id="review-order-date"
              onChange={(event) => updateScalar("orderDate", event.target.value)}
              type="date"
              value={inputValue(candidate.orderDate)}
            />

            <label htmlFor="review-requested-delivery-date">Requested delivery date</label>
            <input
              id="review-requested-delivery-date"
              onChange={(event) => updateScalar("requestedDeliveryDate", event.target.value)}
              type="date"
              value={inputValue(candidate.requestedDeliveryDate)}
            />

            <label htmlFor="review-currency">Currency</label>
            <input
              id="review-currency"
              onChange={(event) => updateScalar("currency", event.target.value)}
              type="text"
              value={inputValue(candidate.currency)}
            />
          </div>

          <fieldset className="review-lines-fieldset">
            <legend>Ordered lines</legend>
            {candidate.lines.length === 0 ? <p>No ordered lines. Add a line if required.</p> : null}
            <div className="review-editable-lines">
              {candidate.lines.map((line, index) => (
                <fieldset className="review-editable-line" key={`line-${index}`}>
                  <legend>Line {index + 1}</legend>
                  <label htmlFor={`review-line-${index}-sku`}>Line {index + 1} SKU</label>
                  <input
                    id={`review-line-${index}-sku`}
                    onChange={(event) => updateLine(index, "sku", event.target.value)}
                    type="text"
                    value={inputValue(line.sku)}
                  />
                  <label htmlFor={`review-line-${index}-description`}>Line {index + 1} description</label>
                  <input
                    id={`review-line-${index}-description`}
                    onChange={(event) => updateLine(index, "description", event.target.value)}
                    type="text"
                    value={inputValue(line.description)}
                  />
                  <label htmlFor={`review-line-${index}-quantity`}>Line {index + 1} quantity</label>
                  <input
                    id={`review-line-${index}-quantity`}
                    inputMode="decimal"
                    onChange={(event) => updateLine(index, "quantity", event.target.value)}
                    type="text"
                    value={inputValue(line.quantity)}
                  />
                  <label htmlFor={`review-line-${index}-submitted-price`}>Line {index + 1} submitted price</label>
                  <input
                    id={`review-line-${index}-submitted-price`}
                    inputMode="decimal"
                    onChange={(event) => updateLine(index, "submittedPrice", event.target.value)}
                    type="text"
                    value={inputValue(line.submittedPrice)}
                  />
                  <div className="review-line-actions">
                    <button disabled={index === 0} onClick={() => moveLine(index, -1)} type="button">Move line {index + 1} up</button>
                    <button disabled={index === candidate.lines.length - 1} onClick={() => moveLine(index, 1)} type="button">Move line {index + 1} down</button>
                    <button onClick={() => removeLine(index)} type="button">Remove line {index + 1}</button>
                  </div>
                </fieldset>
              ))}
            </div>
            <button onClick={addLine} type="button">Add line</button>
          </fieldset>
        </fieldset>

        <button disabled={submitting || reloading} type="submit">
          {submitting ? "Saving & revalidating…" : "Save & revalidate"}
        </button>
      </form>
    </section>
  );
}

export default ReviewDraftForm;
