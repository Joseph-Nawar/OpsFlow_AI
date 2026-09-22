import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReviewApiError } from "../../api/review";
import type { ReviewApiClient, ReviewCommandResult, ReviewDetail } from "../../api/review";
import ReviewActions from "./ReviewActions";

const detail: ReviewDetail = {
  etag: '"review-state-v1-order-001"',
  order: {
    id: "order-001",
    state: "READY_FOR_APPROVAL",
    failureOrigin: null,
    createdAt: "2026-09-19T08:30:00Z",
    customerReference: "CUST-001",
    poNumber: "PO-204",
    orderDate: "2026-09-18",
    requestedDeliveryDate: null,
    currency: "USD",
    lines: [],
  },
  sourceDocuments: [],
  sourceSnapshot: null,
  originalExtraction: null,
  effectiveDraft: null,
  revisions: [],
  latestRevision: null,
  validationIssues: [],
  operator: { actor: "approver-demo", role: "APPROVER" },
  actions: { canEdit: false, canApprove: true, canReject: true, canRetry: false },
};

const commandResult: ReviewCommandResult = {
  orderId: "order-001",
  state: "APPROVED",
  failureOrigin: null,
  etag: '"review-state-v1-approved"',
};

function renderActions(
  overrides: Partial<ReviewDetail> = {},
  apiOverrides: Partial<Pick<ReviewApiClient, "approve" | "reject" | "retry">> = {},
  onReload: () => Promise<boolean> = vi.fn(async () => true),
  onCommandCompleted: (result: ReviewCommandResult) => void = vi.fn(),
) {
  const api: Pick<ReviewApiClient, "approve" | "reject" | "retry"> = {
    approve: vi.fn(async () => commandResult),
    reject: vi.fn(async () => commandResult),
    retry: vi.fn(async () => ({ ...commandResult, state: "PROCESSING" as const })),
    ...apiOverrides,
  };
  render(
    <ReviewActions
      api={api}
      detail={{ ...detail, ...overrides }}
      onCommandCompleted={onCommandCompleted}
      onReload={onReload}
      orderId="order-001"
    />,
  );
  return api;
}

describe("ReviewActions", () => {
  it("renders controls only from backend action flags and does not grant high-value approval", () => {
    renderActions({
      validationIssues: [{
        ruleCode: "HIGH_VALUE_APPROVAL_REQUIRED",
        severity: "WARNING",
        field: null,
        expected: "Elevated approval",
        actual: "High value",
        explanation: "An elevated approver is required.",
      }],
      actions: { canEdit: false, canApprove: false, canReject: true, canRetry: false },
    });

    expect(screen.queryByRole("button", { name: "Approve order" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject order" })).toBeInTheDocument();
    expect(screen.getByText("High-value approval is required; the server controls who may approve.")).toBeInTheDocument();
  });

  it("shows high-value approval only when the server permits it", () => {
    renderActions({
      validationIssues: [{
        ruleCode: "HIGH_VALUE_APPROVAL_REQUIRED",
        severity: "WARNING",
        field: null,
        expected: "Elevated approval",
        actual: "High value",
        explanation: "An elevated approver is required.",
      }],
      operator: { actor: "elevated-demo", role: "ELEVATED_APPROVER" },
      actions: { canEdit: false, canApprove: true, canReject: true, canRetry: false },
    });

    expect(screen.getByRole("button", { name: "Approve order" })).toBeInTheDocument();
    expect(screen.getByText("The server has permitted elevated approval for this high-value order.")).toBeInTheDocument();
  });

  it("approves exactly once with the current ETag and reports the authoritative result", async () => {
    let resolveApproval!: (result: ReviewCommandResult) => void;
    const approve = vi.fn(() => new Promise<ReviewCommandResult>((resolve) => { resolveApproval = resolve; }));
    const onCommandCompleted = vi.fn();
    const api = renderActions({}, { approve }, vi.fn(async () => true), onCommandCompleted);
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Approve order" });

    await user.click(button);
    await user.click(button);

    expect(api.approve).toHaveBeenCalledTimes(1);
    expect(api.approve).toHaveBeenCalledWith("order-001", detail.etag);
    expect(button).toBeDisabled();
    resolveApproval(commandResult);
    await vi.waitFor(() => expect(onCommandCompleted).toHaveBeenCalledWith(commandResult));
  });

  it("requires a bounded labelled rejection reason and sends only reason plus ETag", async () => {
    const reject = vi.fn(async () => commandResult);
    const api = renderActions({ actions: { canEdit: false, canApprove: false, canReject: true, canRetry: false } }, { reject });
    const user = userEvent.setup();
    const reason = screen.getByLabelText("Rejection reason");

    expect(reason).toBeRequired();
    expect(reason).toHaveAttribute("maxLength", "500");
    await user.type(reason, "duplicate order");
    await user.click(screen.getByRole("button", { name: "Reject order" }));

    expect(api.reject).toHaveBeenCalledTimes(1);
    expect(api.reject).toHaveBeenCalledWith("order-001", "duplicate order", detail.etag);
  });

  it("shows retry only when permitted and never exposes a client-selected destination", () => {
    renderActions({
      order: { ...detail.order, state: "FAILED_RETRYABLE", failureOrigin: "EXTRACTED" },
      actions: { canEdit: false, canApprove: false, canReject: false, canRetry: true },
    });

    expect(screen.getByRole("button", { name: "Retry order" })).toBeInTheDocument();
    expect(screen.getByText("Retry only restores the persisted failure origin; resumed processing is outside Phase 6.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/PROCESSING|EXTRACTED|SYNCING/)).not.toBeInTheDocument();
  });

  it("retries exactly once with the current ETag and reports the server result", async () => {
    const retryResult: ReviewCommandResult = {
      orderId: "order-001",
      state: "EXTRACTED",
      failureOrigin: null,
      etag: '"review-state-v1-extracted"',
    };
    const retry = vi.fn(async () => retryResult);
    const onCommandCompleted = vi.fn();
    const api = renderActions(
      {
        order: { ...detail.order, state: "FAILED_RETRYABLE", failureOrigin: "EXTRACTED" },
        actions: { canEdit: false, canApprove: false, canReject: false, canRetry: true },
      },
      { retry },
      vi.fn(async () => true),
      onCommandCompleted,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Retry order" }));

    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("order-001", detail.etag);
    await vi.waitFor(() => expect(onCommandCompleted).toHaveBeenCalledWith(retryResult));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(api.retry).toHaveBeenCalledTimes(1);
  });

  it.each([
    [401, "UNAUTHENTICATED", "Authentication failed."],
    [403, "FORBIDDEN", "You are not permitted to perform this action."],
    [409, "INVALID_REVIEW_STATE", "This review action is not valid for the current order state."],
  ] as const)("keeps %s command errors safe and visible", async (status, code, message) => {
    const approve = vi.fn(async () => {
      throw new ReviewApiError(status, code, message);
    });
    renderActions({}, { approve });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve order" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("locks all command controls after stale 412 until explicit reload succeeds", async () => {
    const approve = vi.fn(async () => {
      throw new ReviewApiError(412, "PRECONDITION_FAILED", "Refresh the review case.");
    });
    const onReload = vi.fn(async () => false);
    const api = renderActions({}, { approve }, onReload);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve order" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This review case changed and must be reloaded.");
    const approveButton = screen.getByRole("button", { name: "Approve order" });
    expect(approveButton).toBeDisabled();
    expect(screen.getByLabelText("Rejection reason")).toBeDisabled();
    await user.click(approveButton);
    expect(api.approve).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Reload review case" }));
    expect(onReload).toHaveBeenCalledTimes(1);
    expect(approveButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload review case" })).toBeInTheDocument();
  });

  it("uses a bounded message for unknown failures", async () => {
    const approve = vi.fn(async () => { throw new Error("raw credentials or provider data"); });
    renderActions({}, { approve });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve order" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to complete this review action. Please try again.");
    expect(screen.queryByText("raw credentials or provider data")).not.toBeInTheDocument();
  });
});
