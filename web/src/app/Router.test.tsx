import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";

import type { OperatorSession, ReviewQueuePage } from "../api/review";
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

beforeEach(() => {
  reviewApiMock.createReviewApiClient.mockReset();
  reviewApiMock.listOrders.mockReset();
  reviewApiMock.listOrders.mockResolvedValue(emptyQueue);
  reviewApiMock.createReviewApiClient.mockReturnValue({
    listOrders: reviewApiMock.listOrders,
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

  it("renders the detail shell with the route order id", () => {
    render(
      <MemoryRouter initialEntries={["/review/order-123"]}>
        <ReviewRouter session={verifiedSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Review case" })).toBeInTheDocument();
    expect(screen.getByText("order-123")).toBeInTheDocument();
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
