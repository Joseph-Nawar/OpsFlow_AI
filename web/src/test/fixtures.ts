import type { ReviewDraft } from "../api/review";

export const queueWireFixture = {
  items: [
    {
      id: "order-001",
      state: "NEEDS_REVIEW",
      failure_origin: null,
      customer_reference: "CUST-001",
      po_number: "PO-204",
      order_date: "2026-09-18",
      requested_delivery_date: null,
      currency: "USD",
      created_at: "2026-09-19T08:30:00Z",
      validation_issue_count: 2,
      high_value_approval_required: false,
    },
  ],
  states: ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "FAILED_RETRYABLE"],
  limit: 25,
  offset: 0,
  total: 1,
} as const;

export const reviewDetailWireFixture = {
  etag: '"review-state-v1-order-001"',
  order: {
    id: "order-001",
    state: "NEEDS_REVIEW",
    failure_origin: null,
    created_at: "2026-09-19T08:30:00Z",
    customer_reference: "CUST-001",
    po_number: "PO-204",
    order_date: "2026-09-18",
    requested_delivery_date: null,
    currency: "USD",
    lines: [
      {
        id: "line-001",
        sku: null,
        description: null,
        quantity: "2",
        submitted_price: null,
        trusted_catalogue_price: null,
      },
    ],
  },
  source_documents: [
    {
      id: "source-001",
      document_type: "EMAIL",
      name: "purchase-order.eml",
      mime_type: "message/rfc822",
      sha256: "a".repeat(64),
      message_id: null,
      storage_reference: null,
      metadata: [
        { key: "sender", value: "buyer@example.invalid" },
        { key: "sender", value: "forwarded@example.invalid" },
      ],
    },
  ],
  source_snapshot: {
    id: "snapshot-001",
    source_document_id: "source-001",
    source_sha256: "a".repeat(64),
    source_document_type: "EMAIL",
    created_at: "2026-09-19T08:30:01Z",
  },
  original_extraction: {
    source_sha256: "a".repeat(64),
    source_document_type: "EMAIL",
    customer_name: "Acme Industries",
    customer_reference: "CUST-001",
    po_number: "PO-204",
    order_date: "2026-09-18",
    requested_delivery_date: null,
    currency: "USD",
    lines: [
      {
        sku: "SKU-001",
        description: "Widget",
        quantity: "2",
        submitted_price: "10.00",
      },
    ],
    notes: null,
    evidence: [
      {
        field_path: "po_number",
        source_location: null,
        quote: null,
      },
    ],
  },
  effective_draft: {
    customer_name: "Acme Industries",
    customer_reference: "CUST-001",
    po_number: "PO-204",
    order_date: "2026-09-18",
    requested_delivery_date: null,
    currency: "USD",
    lines: [
      {
        sku: "SKU-001",
        description: "Widget",
        quantity: "2",
        submitted_price: "10.00",
      },
    ],
    source_snapshot_id: "snapshot-001",
    latest_revision_number: 1,
  },
  revisions: [
    {
      id: "revision-001",
      revision_number: 1,
      actor: "reviewer-demo",
      created_at: "2026-09-19T08:32:00Z",
      changes: [
        {
          field_path: "customer_name",
          old_value: "Acme",
          new_value: "Acme Industries",
        },
        {
          field_path: "lines",
          old_value: [],
          new_value: [{ sku: "SKU-001", quantity: "2" }],
        },
      ],
    },
  ],
  latest_revision: {
    id: "revision-001",
    revision_number: 1,
    actor: "reviewer-demo",
    created_at: "2026-09-19T08:32:00Z",
    changes: [
      {
        field_path: "customer_name",
        old_value: "Acme",
        new_value: "Acme Industries",
      },
      {
        field_path: "lines",
        old_value: [],
        new_value: [{ sku: "SKU-001", quantity: "2" }],
      },
    ],
  },
  validation_issues: [
    {
      rule_code: "PRODUCT_NOT_FOUND",
      severity: "ERROR",
      field: null,
      expected: null,
      actual: { sku: "SKU-001" },
      explanation: "The submitted product needs review.",
    },
  ],
  operator: { actor: "reviewer-demo", role: "REVIEWER" },
  actions: {
    can_edit: true,
    can_approve: false,
    can_reject: true,
    can_retry: false,
  },
} as const;

export const referenceDataWireFixture = {
  label: "Current trusted reference data",
  customer_candidates: [
    { reference: "CUST-001", name: "Acme Industries", active: true },
  ],
  products_by_line: [
    {
      sku: "SKU-001",
      description: null,
      active: true,
      currency: "USD",
      catalogue_price: "10.00",
      available_quantity: "100",
    },
    null,
  ],
} as const;

export const commandWireFixture = {
  order_id: "order-001",
  state: "APPROVED",
  failure_origin: null,
  etag: '"review-state-v1-approved"',
} as const;

export const auditListWireFixture = {
  items: [
    {
      id: "audit-001",
      order_id: "order-001",
      event_type: "ORDER_APPROVED",
      actor: "approver-demo",
      occurred_at: "2026-09-19T08:40:00Z",
      description: "Order approved by operator.",
    },
  ],
} as const;

export const draftFixture: ReviewDraft = {
  customerName: "Acme Industries",
  customerReference: "CUST-001",
  poNumber: "PO-204",
  orderDate: "2026-09-18",
  requestedDeliveryDate: null,
  currency: "USD",
  lines: [
    {
      sku: "SKU-001",
      description: "Widget",
      quantity: "2",
      submittedPrice: "10.00",
    },
  ],
};
