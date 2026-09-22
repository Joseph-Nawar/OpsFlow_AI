import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createReviewApiClient,
  ReviewApiError,
} from "./review";
import {
  auditListWireFixture,
  commandWireFixture,
  draftFixture,
  queueWireFixture,
  referenceDataWireFixture,
  reviewDetailWireFixture,
} from "../test/fixtures";

const session = { credential: "test-only-review-credential" };
const etag = '"review-state-v1-order-001"';

function response(body: unknown, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("review API wire boundary", () => {
  it("requests a bounded queue and maps snake_case queue values once", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(queueWireFixture));
    const client = createReviewApiClient(session, fetchMock);

    const page = await client.listOrders({
      states: ["NEEDS_REVIEW", "READY_FOR_APPROVAL"],
      limit: 25,
      offset: 5,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/review/orders?states=NEEDS_REVIEW&states=READY_FOR_APPROVAL&limit=25&offset=5");
    expect(init.method ?? "GET").toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-only-review-credential");
    expect(page).toEqual({
      items: [
        {
          id: "order-001",
          state: "NEEDS_REVIEW",
          failureOrigin: null,
          customerReference: "CUST-001",
          poNumber: "PO-204",
          orderDate: "2026-09-18",
          requestedDeliveryDate: null,
          currency: "USD",
          createdAt: "2026-09-19T08:30:00Z",
          validationIssueCount: 2,
          highValueApprovalRequired: false,
        },
      ],
      states: ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "FAILED_RETRYABLE"],
      limit: 25,
      offset: 0,
      total: 1,
    });
  });

  it("maps the exact detail shape, preserving nullable and distinct source data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(reviewDetailWireFixture, { ETag: etag }));
    const client = createReviewApiClient(session, fetchMock);

    const detail = await client.getDetail("order-001");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/review/orders/order-001");
    expect(init.method ?? "GET").toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-only-review-credential");
    expect(detail).toEqual({
      etag,
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
        lines: [
          {
            id: "line-001",
            sku: null,
            description: null,
            quantity: "2",
            submittedPrice: null,
            trustedCataloguePrice: null,
          },
        ],
      },
      sourceDocuments: [
        {
          id: "source-001",
          documentType: "EMAIL",
          name: "purchase-order.eml",
          mimeType: "message/rfc822",
          sha256: "a".repeat(64),
          messageId: null,
          storageReference: null,
          metadata: [
            { key: "sender", value: "buyer@example.invalid" },
            { key: "sender", value: "forwarded@example.invalid" },
          ],
        },
      ],
      sourceSnapshot: {
        id: "snapshot-001",
        sourceDocumentId: "source-001",
        sourceSha256: "a".repeat(64),
        sourceDocumentType: "EMAIL",
        createdAt: "2026-09-19T08:30:01Z",
      },
      originalExtraction: {
        sourceSha256: "a".repeat(64),
        sourceDocumentType: "EMAIL",
        customerName: "Acme Industries",
        customerReference: "CUST-001",
        poNumber: "PO-204",
        orderDate: "2026-09-18",
        requestedDeliveryDate: null,
        currency: "USD",
        lines: [
          { sku: "SKU-001", description: "Widget", quantity: "2", submittedPrice: "10.00" },
        ],
        notes: null,
        evidence: [{ fieldPath: "po_number", sourceLocation: null, quote: null }],
      },
      effectiveDraft: {
        customerName: "Acme Industries",
        customerReference: "CUST-001",
        poNumber: "PO-204",
        orderDate: "2026-09-18",
        requestedDeliveryDate: null,
        currency: "USD",
        lines: [
          { sku: "SKU-001", description: "Widget", quantity: "2", submittedPrice: "10.00" },
        ],
        sourceSnapshotId: "snapshot-001",
        latestRevisionNumber: 1,
      },
      revisions: [
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
      ],
      latestRevision: {
        id: "revision-001",
        revisionNumber: 1,
        actor: "reviewer-demo",
        createdAt: "2026-09-19T08:32:00Z",
        changes: [
          { fieldPath: "customer_name", oldValue: "Acme", newValue: "Acme Industries" },
          { fieldPath: "lines", oldValue: [], newValue: [{ sku: "SKU-001", quantity: "2" }] },
        ],
      },
      validationIssues: [
        {
          ruleCode: "PRODUCT_NOT_FOUND",
          severity: "ERROR",
          field: null,
          expected: null,
          actual: { sku: "SKU-001" },
          explanation: "The submitted product needs review.",
        },
      ],
      operator: { actor: "reviewer-demo", role: "REVIEWER" },
      actions: { canEdit: true, canApprove: false, canReject: true, canRetry: false },
    });
    expect(detail.sourceDocuments[0].metadata).toHaveLength(2);
    expect("payload" in detail.revisions[0]).toBe(false);
    expect("snapshotId" in detail.originalExtraction!).toBe(false);
  });

  it("keeps operator presentation data out of all client authority claims", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(queueWireFixture));
    const client = createReviewApiClient(
      { credential: "test-only-review-credential", operator: { actor: "server-actor", role: "APPROVER" } },
      fetchMock,
    );

    await client.listOrders({ states: [], limit: 1, offset: 0 });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).not.toContain("test-only-review-credential");
    expect([...headers.keys()]).toEqual(["authorization"]);
    expect(headers.get("Authorization")).toBe("Bearer test-only-review-credential");
  });

  it("keeps pre-extraction retry cases null instead of inventing source or draft data", async () => {
    const noSnapshotDetail = {
      ...reviewDetailWireFixture,
      order: {
        ...reviewDetailWireFixture.order,
        state: "FAILED_RETRYABLE",
        failure_origin: "PROCESSING",
        lines: [],
      },
      source_documents: [],
      source_snapshot: null,
      original_extraction: null,
      effective_draft: null,
      revisions: [],
      latest_revision: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(response(noSnapshotDetail, { ETag: etag }));

    const detail = await createReviewApiClient(session, fetchMock).getDetail("order-001");

    expect(detail.sourceDocuments).toEqual([]);
    expect(detail.sourceSnapshot).toBeNull();
    expect(detail.originalExtraction).toBeNull();
    expect(detail.effectiveDraft).toBeNull();
    expect(detail.latestRevision).toBeNull();
  });

  it("maps labeled reference data including nullable product slots", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(referenceDataWireFixture));
    const result = await createReviewApiClient(session, fetchMock).getReferenceData("order-001");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/review/orders/order-001/reference-data");
    expect(init.method ?? "GET").toBe("GET");
    expect(result).toEqual({
      label: "Current trusted reference data",
      customerCandidates: [{ reference: "CUST-001", name: "Acme Industries", active: true }],
      productsByLine: [
        {
          sku: "SKU-001",
          description: null,
          active: true,
          currency: "USD",
          cataloguePrice: "10.00",
          availableQuantity: "100",
        },
        null,
      ],
    });
  });

  it("sends only editable fields with bearer and If-Match and captures the returned ETag", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(reviewDetailWireFixture, { ETag: etag }));
    const previousEtag = '"review-state-v1-before-save"';
    const result = await createReviewApiClient(session, fetchMock).saveDraft("order-001", draftFixture, previousEtag);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/v1/review/orders/order-001/draft");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-only-review-credential");
    expect(new Headers(init.headers).get("If-Match")).toBe(previousEtag);
    expect(JSON.parse(String(init.body))).toEqual({
      customer_name: "Acme Industries",
      customer_reference: "CUST-001",
      po_number: "PO-204",
      order_date: "2026-09-18",
      requested_delivery_date: null,
      currency: "USD",
      lines: [{ sku: "SKU-001", description: "Widget", quantity: "2", submitted_price: "10.00" }],
    });
    expect(result.etag).toBe(etag);
  });

  it.each([
    ["approve", "POST", "/v1/review/orders/order-001/approve", undefined],
    ["reject", "POST", "/v1/review/orders/order-001/reject", { reason: "duplicate order" }],
    ["retry", "POST", "/v1/review/orders/order-001/retry", undefined],
  ] as const)("maps %s command and always sends If-Match", async (methodName, method, url, body) => {
    const fetchMock = vi.fn().mockResolvedValue(response(commandWireFixture, { ETag: commandWireFixture.etag }));
    const client = createReviewApiClient(session, fetchMock);
    const result = methodName === "approve"
      ? await client.approve("order-001", etag)
      : methodName === "reject"
        ? await client.reject("order-001", "duplicate order", etag)
        : await client.retry("order-001", etag);
    const [actualUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(actualUrl).toBe(url);
    expect(init.method).toBe(method);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-only-review-credential");
    expect(new Headers(init.headers).get("If-Match")).toBe(etag);
    expect(init.body).toBe(body === undefined ? undefined : JSON.stringify(body));
    expect(result).toEqual({ orderId: "order-001", state: "APPROVED", failureOrigin: null, etag: commandWireFixture.etag });
  });

  it("unwraps the existing audit items envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(auditListWireFixture));
    const events = await createReviewApiClient(session, fetchMock).getAudit("order-001");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/orders/order-001/audit");
    expect(init.method ?? "GET").toBe("GET");
    expect(events).toEqual([
      {
        id: "audit-001",
        orderId: "order-001",
        eventType: "ORDER_APPROVED",
        actor: "approver-demo",
        occurredAt: "2026-09-19T08:40:00Z",
        description: "Order approved by operator.",
      },
    ]);
  });

  it("parses only bounded structured errors and never returns raw payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: "PRECONDITION_FAILED", message: "Refresh the review case.", secret: "raw-token" }, raw: "raw body" }),
      { status: 412, headers: { "Content-Type": "application/json" } },
    ));
    const client = createReviewApiClient(session, fetchMock);

    const structuredError = await client.getDetail("order-001").catch((error: unknown) => error);
    expect(structuredError).toBeInstanceOf(ReviewApiError);
    expect(structuredError).toMatchObject({
      name: "ReviewApiError",
      status: 412,
      code: "PRECONDITION_FAILED",
      message: "Refresh the review case.",
    });
    expect(String(structuredError)).not.toContain("raw-token");
    expect(String(structuredError)).not.toContain("raw body");

    const oversizedFetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: "X".repeat(120), message: "Y".repeat(1000) } }),
      { status: 503 },
    ));
    await expect(createReviewApiClient(session, oversizedFetch).getDetail("order-001"))
      .rejects.toMatchObject({ code: "API_ERROR", message: "The review request failed." });
  });

  it("rejects a detail whose ETag header disagrees with its body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(reviewDetailWireFixture, { ETag: '"different-generation"' }));

    await expect(createReviewApiClient(session, fetchMock).getDetail("order-001"))
      .rejects.toMatchObject({
        status: 200,
        code: "INVALID_RESPONSE",
        message: "The review response validator is inconsistent.",
      });
  });
});
