import { useState, type FormEvent } from "react";

import {
  createReviewApiClient,
  ReviewApiError,
  type OperatorSession,
} from "../api/review";
import { readOperatorCredential, storeOperatorCredential } from "./operatorAccess";

interface OperatorAccessFormProps {
  onAuthenticated: (session: OperatorSession) => void;
}

const ACCESS_CHECK_STATES = ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "FAILED_RETRYABLE"] as const;

function OperatorAccessForm({ onAuthenticated }: OperatorAccessFormProps) {
  const [credential, setCredential] = useState(readOperatorCredential);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createReviewApiClient({ credential }).listOrders({
        states: [...ACCESS_CHECK_STATES],
        limit: 1,
        offset: 0,
      });
      storeOperatorCredential(credential);
      onAuthenticated({ credential });
    } catch (requestError) {
      if (requestError instanceof ReviewApiError && requestError.status === 401) {
        setError("Authentication failed. Check the configured development credential.");
      } else {
        setError("The review service could not verify access. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="access-shell">
      <form className="access-card" onSubmit={connect}>
        <p className="eyebrow">OpsFlow AI · Development access</p>
        <h1>Connect to review</h1>
        <p className="access-copy">
          Enter a configured development bearer credential. The server determines the operator and role.
        </p>
        <label htmlFor="operator-credential">Development bearer credential</label>
        <input
          autoComplete="off"
          id="operator-credential"
          name="credential"
          onChange={(event) => setCredential(event.currentTarget.value)}
          required
          type="password"
          value={credential}
        />
        <button disabled={submitting} type="submit">
          {submitting ? "Connecting…" : "Connect"}
        </button>
        {error !== null && <p className="form-error" role="alert">{error}</p>}
        <p className="access-note">Local demo authentication only; this is not a production identity system.</p>
      </form>
    </main>
  );
}

export default OperatorAccessForm;
