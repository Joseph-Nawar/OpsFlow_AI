import { Route, Routes, useParams } from "react-router";

function ReviewQueueShell() {
  return (
    <main className="foundation">
      <p className="eyebrow">OpsFlow AI · Human review</p>
      <h1>Review queue</h1>
      <p>Review application foundation.</p>
    </main>
  );
}

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

function ReviewRouter() {
  return (
    <Routes>
      <Route element={<ReviewQueueShell />} path="/review" />
      <Route element={<ReviewCaseShell />} path="/review/:orderId" />
    </Routes>
  );
}

export default ReviewRouter;
