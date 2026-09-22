import { useMemo } from "react";
import { Route, Routes, useParams } from "react-router";

import type { OperatorSession } from "../api/review";
import { createReviewApiClient } from "../api/review";
import ReviewQueuePage from "../pages/ReviewQueuePage";

function ReviewCaseShell() {
  const { orderId } = useParams();
  return (
    <main className="foundation">
      <p className="eyebrow">OpsFlow AI · Human review</p>
      <h1>Review case</h1>
      <p>{orderId}</p>
    </main>
  );
}

interface ReviewRouterProps {
  session: OperatorSession;
}

function ReviewRouter({ session }: ReviewRouterProps) {
  const apiClient = useMemo(() => createReviewApiClient(session), [session]);

  return (
    <Routes>
      <Route element={<ReviewQueuePage api={apiClient} />} path="/review" />
      <Route element={<ReviewCaseShell />} path="/review/:orderId" />
    </Routes>
  );
}

export default ReviewRouter;
