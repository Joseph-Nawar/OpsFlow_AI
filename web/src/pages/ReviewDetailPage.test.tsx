import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ReviewApiClient, ReviewDetail, ReviewQueuePage } from "../api/review";
import ReviewDetailPage from "./ReviewDetailPage";

const detail: ReviewDetail = {
  etag: '"review-state-v1-order-001"',
  order: {
    id: "order-001",
    state: "NEEDS_REVIEW",
    failureOrigin: null,
    createdAt: "2026-09-19T08:30:00Z",
    customerReference: "CUST-001",
    poNumber: "PO-204",
    orderDate: "2026-09-18",
    requestedDeliveryDate: null,
    currency: "USD",
    lines: [{
      id: "line-001",
      sku: "SKU-001",
      description: "Widget",
      quantity: "2",
      submittedPrice: "10.00",
      trustedCataloguePrice: "10.00",
    }],
  },
  sourceDocuments: [],
  sourceSnapshot: null,
  originalExtraction: null,
  effectiveDraft: {
    customerName: "Acme Industries",
    customerReference: "CUST-001",
    poNumber: "PO-204",
    orderDate: "2026-09-18",
    requestedDeliveryDate: null,
    currency: "USD",
    lines: [{ sku: "SKU-001", description: "Widget", quantity: "2", submittedPrice: "10.00" }],
    sourceSnapshotId: null,
    latestRevisionNumber: 1,
  },
  revisions: [{
    id: "revision-001",
    revisionNumber: 1,
    actor: "reviewer-demo",
    createdAt: "2026-09-19T08:32:00Z",
    changes: [{ fieldPath: "customer_name", oldValue: "Acme", newValue: "Acme Industries" }],
  }],
  latestRevision: null,
  validationIssues: [{
    ruleCode: "PRODUCT_NOT_FOUND",
    severity: "ERROR",
    field: null,
    expected: null,
    actual: { sku: "SKU-001" },
    explanation: "The submitted product needs review.",
  }],
  operator: { actor: "reviewer-demo", role: "REVIEWER" },
  actions: { canEdit: true, canApprove: false, canReject: true, canRetry: false },
};

const referenceData = {
  label: "Current trusted reference data",
  customerCandidates: [{ reference: "CUST-001", name: "Acme Industries", active: true }],
  productsByLine: [{
    sku: "SKU-001",
    description: "Widget",
    active: true,
    currency: "USD",
    cataloguePrice: "10.00",
    availableQuantity: "100",
  }],
};

function apiDouble(overrides: Partial<ReviewApiClient> = {}): ReviewApiClient {
  return {
    listOrders: vi.fn(async (): Promise<ReviewQueuePage> => ({
      items: [],
      states: ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "FAILED_RETRYABLE"],
      limit: 50,
      offset: 0,
      total: 0,
    })),
    getDetail: vi.fn(async () => detail),
    getReferenceData: vi.fn(async () => referenceData),
    saveDraft: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    retry: vi.fn(),
    getAudit: vi.fn(async () => []),
    ...overrides,
  };
}

function renderDetail(api: ReviewApiClient, orderId = "order-001") {
  return render(
    <MemoryRouter initialEntries={[`/review/${orderId}`]}>
      <Routes>
        <Route element={<ReviewDetailPage api={api} />} path="/review/:orderId" />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReviewDetailPage", () => {
  it("shows loading while loading the route order detail", () => {
    let resolveDetail!: (value: ReviewDetail) => void;
    const pending = new Promise<ReviewDetail>((resolve) => { resolveDetail = resolve; });
    const api = apiDouble({ getDetail: vi.fn(() => pending) });

    renderDetail(api, "order-123");

    expect(screen.getByRole("status")).toHaveTextContent("Loading review case");
    resolveDetail(detail);
  });

  it("renders distinct provenance, human, trusted, validation, operator, and action sections", async () => {
    const audit = [{
      id: "audit-001",
      orderId: "order-001",
      eventType: "ORDER_REJECTED",
      actor: "reviewer-demo",
      occurredAt: "2026-09-19T08:40:00Z",
      description: "Order rejected.",
    }];
    const api = apiDouble({ getAudit: vi.fn(async () => audit) });

    renderDetail(api);

    expect(await screen.findByRole("heading", { name: "Review case order-001" })).toBeInTheDocument();
    expect(screen.getByText("State: NEEDS_REVIEW")).toBeInTheDocument();
    expect(screen.getByText("HUMAN-REVIEWED effective values (untrusted candidate)")).toBeInTheDocument();
    expect(screen.getByText("TRUSTED persisted order")).toBeInTheDocument();
    expect(screen.getByText("DETERMINISTIC validation results")).toBeInTheDocument();
    expect(screen.getByText("PRODUCT_NOT_FOUND")).toBeInTheDocument();
    expect(screen.getByText("The submitted product needs review.")).toBeInTheDocument();
    expect(screen.getByText("Operator: reviewer-demo (REVIEWER)")).toBeInTheDocument();
    expect(screen.getByText("Can approve: No")).toBeInTheDocument();
    expect(screen.getByText("Action flags are informational; the server remains authoritative.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Current trusted reference data" })).toBeInTheDocument();
    expect(await screen.findByText("ORDER_REJECTED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|reject|retry/i })).not.toBeInTheDocument();
  });

  it("renders a bounded detail error and retries without exposing raw errors", async () => {
    const api = apiDouble({
      getDetail: vi.fn()
        .mockRejectedValueOnce(new Error("raw SQL or provider response"))
        .mockResolvedValueOnce(detail),
    });
    const user = userEvent.setup();

    renderDetail(api);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load this review case. Please try again.",
    );
    expect(screen.queryByText("raw SQL or provider response")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry review case" }));
    expect(await screen.findByText("TRUSTED persisted order")).toBeInTheDocument();
  });

  it("keeps a pre-extraction case safe when source and effective draft are absent", async () => {
    const preExtraction = {
      ...detail,
      order: { ...detail.order, state: "FAILED_RETRYABLE" as const, failureOrigin: "EXTRACTED" as const },
      sourceSnapshot: null,
      sourceDocuments: [],
      originalExtraction: null,
      effectiveDraft: null,
    };
    const api = apiDouble({ getDetail: vi.fn(async () => preExtraction) });

    renderDetail(api);

    expect(await screen.findByText("No original AI extraction is available for this review case.")).toBeInTheDocument();
    expect(screen.getByText("No human-reviewed effective draft is available.")).toBeInTheDocument();
    expect(screen.getByText("No source snapshot is available.")).toBeInTheDocument();
  });

  it("keeps audit failure isolated while the loaded detail remains usable", async () => {
    const api = apiDouble({ getAudit: vi.fn(async () => { throw new Error("audit secret"); }) });

    renderDetail(api);

    expect(await screen.findByText("TRUSTED persisted order")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load order audit history");
    expect(screen.queryByText("audit secret")).not.toBeInTheDocument();
  });
});
