import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AuditEvent, ReviewApiClient, ReviewRevision } from "../../api/review";
import ReviewHistoryPanel from "./ReviewHistoryPanel";

const revisions: ReviewRevision[] = [
  {
    id: "revision-001",
    revisionNumber: 1,
    actor: "reviewer-demo",
    createdAt: "2026-09-19T08:32:00Z",
    changes: [
      { fieldPath: "customer_name", oldValue: "Acme", newValue: "Acme Industries" },
      { fieldPath: "lines", oldValue: [], newValue: [{ sku: "SKU-001", quantity: "2" }] },
    ],
  },
];

const auditEvents: AuditEvent[] = [
  {
    id: "audit-001",
    orderId: "order-001",
    eventType: "REVIEW_REVISION_RECORDED",
    actor: "reviewer-demo",
    occurredAt: "2026-09-19T08:32:01Z",
    description: "Review revision recorded.",
  },
];

function apiDouble(
  getAudit: ReviewApiClient["getAudit"],
): Pick<ReviewApiClient, "getAudit"> {
  return { getAudit };
}

describe("ReviewHistoryPanel", () => {
  it("renders structured revision changes separately from order audit events", async () => {
    const api = apiDouble(vi.fn(async () => auditEvents));

    render(<ReviewHistoryPanel api={api} orderId="order-001" revisions={revisions} />);

    expect(screen.getByRole("heading", { name: "Human review revisions" })).toBeInTheDocument();
    expect(screen.getByText("Revision 1 · revision-001")).toBeInTheDocument();
    expect(screen.getByText("2026-09-19T08:32:00Z · reviewer-demo")).toBeInTheDocument();
    expect(screen.getByText("customer_name")).toBeInTheDocument();
    expect(screen.getByText("Acme Industries")).toBeInTheDocument();
    expect(screen.getByText(/\{"sku":"SKU-001","quantity":"2"\}/)).toBeInTheDocument();
    expect(screen.queryByText("payload")).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Order audit history" })).toBeInTheDocument();
    expect(api.getAudit).toHaveBeenCalledWith("order-001");
    expect(screen.getByText("REVIEW_REVISION_RECORDED")).toBeInTheDocument();
    expect(screen.getByText("Review revision recorded.")).toBeInTheDocument();
  });

  it("isolates audit failure from usable revision history and provides retry", async () => {
    const api = apiDouble(vi.fn()
      .mockRejectedValueOnce(new Error("raw audit response"))
      .mockResolvedValueOnce(auditEvents));
    const user = userEvent.setup();

    render(<ReviewHistoryPanel api={api} orderId="order-001" revisions={revisions} />);

    expect(screen.getByText("Revision 1 · revision-001")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load order audit history. Please try again.",
    );
    expect(screen.queryByText("raw audit response")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry audit history" }));
    await waitFor(() => expect(api.getAudit).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("REVIEW_REVISION_RECORDED")).toBeInTheDocument();
  });

  it("renders explicit empty states for both histories", async () => {
    const api = apiDouble(vi.fn(async () => []));

    render(<ReviewHistoryPanel api={api} orderId="order-001" revisions={[]} />);

    expect(screen.getByText("No human review revisions recorded.")).toBeInTheDocument();
    expect(await screen.findByText("No order audit events recorded.")).toBeInTheDocument();
  });
});
