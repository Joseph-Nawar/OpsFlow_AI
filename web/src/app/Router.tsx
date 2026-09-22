import { useMemo } from "react";
import { Route, Routes } from "react-router";

import type { OperatorSession } from "../api/review";
import { createReviewApiClient } from "../api/review";
import ReviewDetailPage from "../pages/ReviewDetailPage";
import ReviewQueuePage from "../pages/ReviewQueuePage";

interface ReviewRouterProps {
  session: OperatorSession;
}

function ReviewRouter({ session }: ReviewRouterProps) {
  const apiClient = useMemo(() => createReviewApiClient(session), [session]);

  return (
    <Routes>
      <Route element={<ReviewQueuePage api={apiClient} />} path="/review" />
      <Route element={<ReviewDetailPage api={apiClient} />} path="/review/:orderId" />
    </Routes>
  );
}

export default ReviewRouter;
