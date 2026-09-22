import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";

import type { OperatorSession, ReviewDetail, ReviewQueuePage } from "../api/review";
import ReviewRouter from "./Router";

const reviewApiMock = vi.hoisted(() => ({
  createReviewApiClient: vi.fn(),
  listOrders: vi.fn(),
}));

vi.mock("../api/review", async () => {
  const actual = await vi.importActual<typeof import("../api/review")>("../api/review");
  return { ...actual, createReviewApiClient: reviewApiMock.createReviewApiClient };
});

const verifiedSession: OperatorSession = {
  credential: "session-only-test-credential",
  operator: { actor: "reviewer-demo", role: "REVIEWER" },
};

const emptyQueue: ReviewQueuePage = {
  items: [],
  states: ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "FAILED_RETRYABLE"],
  limit: 50,
  offset: 0,
  total: 0,
};

const routeDetail: ReviewDetail = {
  etag: '"review-state-v1-order-123"',
  order: {
    id: "order-123",
    state: "NEEDS_REVIEW",
    failureOrigin: null,
    createdAt: "2026-09-19T08:30:00Z",
    customerReference: null,
    poNumber: null,
    orderDate: null,
    requestedDeliveryDate: null,
    currency: null,
    lines: [],
  },
  sourceDocuments: [],
  sourceSnapshot: null,
  originalExtraction: null,
  effectiveDraft: null,
  revisions: [],
  latestRevision: null,
  validationIssues: [],
  operator: { actor: "reviewer-demo", role: "REVIEWER" },
  actions: { canEdit: true, canApprove: false, canReject: true, canRetry: false },
};

beforeEach(() => {
  reviewApiMock.createReviewApiClient.mockReset();
  reviewApiMock.listOrders.mockReset();
  reviewApiMock.listOrders.mockResolvedValue(emptyQueue);
  reviewApiMock.createReviewApiClient.mockReturnValue({
    listOrders: reviewApiMock.listOrders,
    getDetail: vi.fn(async () => routeDetail),
    getReferenceData: vi.fn(async () => ({ label: "Current trusted reference data", customerCandidates: [], productsByLine: [] })),
    getAudit: vi.fn(async () => []),
  });
});

describe("review route shell", () => {
  it("renders the queue shell only at /review", () => {
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <ReviewRouter session={verifiedSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review case" })).not.toBeInTheDocument();
  });

  it("renders the detail route with the route order id", async () => {
    render(
      <MemoryRouter initialEntries={["/review/order-123"]}>
        <ReviewRouter session={verifiedSession} />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Review case order-123" })).toBeInTheDocument();
  });

  it("does not introduce additional review routes", () => {
    render(
      <MemoryRouter initialEntries={["/review/order-123/actions"]}>
        <ReviewRouter session={verifiedSession} />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("heading", { name: "Review queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review case" })).not.toBeInTheDocument();
  });

  it("uses the already verified session passed by App to create the API client", () => {
    window.sessionStorage.setItem("opsflow.review.developmentCredential", "storage-only-credential");

    render(
      <MemoryRouter initialEntries={["/review"]}>
        <ReviewRouter session={verifiedSession} />
      </MemoryRouter>,
    );

    expect(reviewApiMock.createReviewApiClient).toHaveBeenCalledWith(verifiedSession);
    window.sessionStorage.removeItem("opsflow.review.developmentCredential");
  });
});
