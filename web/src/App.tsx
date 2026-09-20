import { useState } from "react";
import { BrowserRouter } from "react-router";

import type { OperatorSession } from "./api/review";
import ReviewRouter from "./app/Router";
import OperatorAccessForm from "./auth/OperatorAccessForm";
import { clearOperatorCredential } from "./auth/operatorAccess";

function App() {
  const [session, setSession] = useState<OperatorSession | null>(null);

  if (session === null) {
    return <OperatorAccessForm onAuthenticated={setSession} />;
  }

  return (
    <BrowserRouter>
      <header className="session-bar">
        <span>Development review access verified by the server.</span>
        <button
          onClick={() => {
            clearOperatorCredential();
            setSession(null);
          }}
          type="button"
        >
          Sign out
        </button>
      </header>
      <ReviewRouter />
    </BrowserRouter>
  );
}

export default App;
