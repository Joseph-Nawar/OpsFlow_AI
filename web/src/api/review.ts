export type ReviewState =
  | "NEEDS_REVIEW"
  | "READY_FOR_APPROVAL"
  | "FAILED_RETRYABLE";

export type OrderState =
  | "RECEIVED"
  | "PROCESSING"
  | "EXTRACTED"
  | "VALIDATED"
  | "NEEDS_REVIEW"
  | "READY_FOR_APPROVAL"
  | "APPROVED"
  | "SYNCING"
  | "COMPLETED"
  | "REJECTED"
  | "FAILED_RETRYABLE"
  | "FAILED_FINAL";

export type OperatorRole = "REVIEWER" | "APPROVER" | "ELEVATED_APPROVER";

export type CanonicalJsonValue =
  | null
  | string
  | number
  | boolean
  | CanonicalJsonValue[]
  | { [key: string]: CanonicalJsonValue };

export interface ReviewQueueQuery {
  states: ReviewState[];
  limit: number;
  offset: number;
}

export interface ReviewQueueItem {
  id: string;
  state: ReviewState;
  failureOrigin: OrderState | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  createdAt: string;
  validationIssueCount: number;
  highValueApprovalRequired: boolean;
}

export interface ReviewQueuePage {
  items: ReviewQueueItem[];
  states: ReviewState[];
  limit: number;
  offset: number;
  total: number;
}

export interface ReviewLine {
  sku: string | null;
  description: string | null;
  quantity: string | null;
  submittedPrice: string | null;
}

export interface ReviewDraft {
  customerName: string | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: ReviewLine[];
}

export interface ReviewChange {
  fieldPath: string;
  oldValue: CanonicalJsonValue;
  newValue: CanonicalJsonValue;
}

export interface ReviewRevision {
  id: string;
  revisionNumber: number;
  changes: ReviewChange[];
  actor: string;
  createdAt: string;
}

export interface SourceDocument {
  id: string;
  documentType: string;
  name: string;
  mimeType: string;
  sha256: string;
  messageId: string | null;
  storageReference: string | null;
  metadata: Array<{ key: string; value: string }>;
}

export interface ExtractionEvidence {
  fieldPath: string;
  sourceLocation: string | null;
  quote: string | null;
}

export interface SourceSnapshot {
  id: string;
  sourceDocumentId: string;
  sourceSha256: string;
  sourceDocumentType: string;
  createdAt: string;
}

export interface OriginalExtraction {
  sourceSha256: string;
  sourceDocumentType: string;
  customerName: string | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: ReviewLine[];
  notes: string | null;
  evidence: ExtractionEvidence[];
}

export interface TrustedOrderLine {
  id: string;
  sku: string | null;
  description: string | null;
  quantity: string;
  submittedPrice: string | null;
  trustedCataloguePrice: string | null;
}

export interface TrustedOrder {
  id: string;
  state: OrderState;
  failureOrigin: OrderState | null;
  createdAt: string;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: TrustedOrderLine[];
}

export interface ValidationIssue {
  ruleCode: string;
  severity: string;
  field: string | null;
  expected: CanonicalJsonValue;
  actual: CanonicalJsonValue;
  explanation: string;
}

export interface ReviewEffectiveDraft extends ReviewDraft {
  sourceSnapshotId: string | null;
  latestRevisionNumber: number | null;
}

export interface ReviewActions {
  canEdit: boolean;
  canApprove: boolean;
  canReject: boolean;
  canRetry: boolean;
}

export interface ReviewDetail {
  etag: string;
  order: TrustedOrder;
  sourceDocuments: SourceDocument[];
  sourceSnapshot: SourceSnapshot | null;
  originalExtraction: OriginalExtraction | null;
  effectiveDraft: ReviewEffectiveDraft | null;
  revisions: ReviewRevision[];
  latestRevision: ReviewRevision | null;
  validationIssues: ValidationIssue[];
  operator: { actor: string; role: OperatorRole };
  actions: ReviewActions;
}

export interface ReferenceData {
  label: string;
  customerCandidates: Array<{
    reference: string;
    name: string;
    active: boolean;
  }>;
  productsByLine: Array<{
    sku: string;
    description: string | null;
    active: boolean;
    currency: string;
    cataloguePrice: string | null;
    availableQuantity: string | null;
  } | null>;
}

export interface AuditEvent {
  id: string;
  orderId: string;
  eventType: string;
  actor: string;
  occurredAt: string;
  description: string;
}

export interface ReviewCommandResult {
  orderId: string;
  state: OrderState;
  failureOrigin: OrderState | null;
  etag: string;
}

export interface OperatorSession {
  credential: string;
  operator?: { actor: string; role: OperatorRole } | null;
}

export class ReviewApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ReviewApiError";
  }
}

export interface ReviewApiClient {
  listOrders(query: ReviewQueueQuery): Promise<ReviewQueuePage>;
  getDetail(orderId: string): Promise<ReviewDetail>;
  getReferenceData(orderId: string): Promise<ReferenceData>;
  saveDraft(orderId: string, draft: ReviewDraft, etag: string): Promise<ReviewDetail>;
  approve(orderId: string, etag: string): Promise<ReviewCommandResult>;
  reject(orderId: string, reason: string, etag: string): Promise<ReviewCommandResult>;
  retry(orderId: string, etag: string): Promise<ReviewCommandResult>;
  getAudit(orderId: string): Promise<AuditEvent[]>;
}

interface WireReviewQueueItem {
  id: string;
  state: ReviewState;
  failure_origin: OrderState | null;
  customer_reference: string | null;
  po_number: string | null;
  order_date: string | null;
  requested_delivery_date: string | null;
  currency: string | null;
  created_at: string;
  validation_issue_count: number;
  high_value_approval_required: boolean;
}

interface WireReviewQueuePage {
  items: WireReviewQueueItem[];
  states: ReviewState[];
  limit: number;
  offset: number;
  total: number;
}

interface WireReviewLine {
  sku: string | null;
  description: string | null;
  quantity: string | null;
  submitted_price: string | null;
}

interface WireReviewDraftRequest {
  customer_name: string | null;
  customer_reference: string | null;
  po_number: string | null;
  order_date: string | null;
  requested_delivery_date: string | null;
  currency: string | null;
  lines: WireReviewLine[];
}

interface WireReviewEffectiveDraft extends WireReviewDraftRequest {
  source_snapshot_id: string | null;
  latest_revision_number: number | null;
}

interface WireReviewChange {
  field_path: string;
  old_value: CanonicalJsonValue;
  new_value: CanonicalJsonValue;
}

interface WireReviewRevision {
  id: string;
  revision_number: number;
  actor: string;
  created_at: string;
  changes: WireReviewChange[];
}

interface WireSourceDocument {
  id: string;
  document_type: string;
  name: string;
  mime_type: string;
  sha256: string;
  message_id: string | null;
  storage_reference: string | null;
  metadata: Array<{ key: string; value: string }>;
}

interface WireExtractionEvidence {
  field_path: string;
  source_location: string | null;
  quote: string | null;
}

interface WireSourceSnapshot {
  id: string;
  source_document_id: string;
  source_sha256: string;
  source_document_type: string;
  created_at: string;
}

interface WireOriginalExtraction {
  source_sha256: string;
  source_document_type: string;
  customer_name: string | null;
  customer_reference: string | null;
  po_number: string | null;
  order_date: string | null;
  requested_delivery_date: string | null;
  currency: string | null;
  lines: WireReviewLine[];
  notes: string | null;
  evidence: WireExtractionEvidence[];
}

interface WireTrustedOrderLine {
  id: string;
  sku: string | null;
  description: string | null;
  quantity: string;
  submitted_price: string | null;
  trusted_catalogue_price: string | null;
}

interface WireTrustedOrder {
  id: string;
  state: OrderState;
  failure_origin: OrderState | null;
  created_at: string;
  customer_reference: string | null;
  po_number: string | null;
  order_date: string | null;
  requested_delivery_date: string | null;
  currency: string | null;
  lines: WireTrustedOrderLine[];
}

interface WireValidationIssue {
  rule_code: string;
  severity: string;
  field: string | null;
  expected: CanonicalJsonValue;
  actual: CanonicalJsonValue;
  explanation: string;
}

interface WireReviewActions {
  can_edit: boolean;
  can_approve: boolean;
  can_reject: boolean;
  can_retry: boolean;
}

interface WireReviewDetail {
  etag: string;
  order: WireTrustedOrder;
  source_documents: WireSourceDocument[];
  source_snapshot: WireSourceSnapshot | null;
  original_extraction: WireOriginalExtraction | null;
  effective_draft: WireReviewEffectiveDraft | null;
  revisions: WireReviewRevision[];
  latest_revision: WireReviewRevision | null;
  validation_issues: WireValidationIssue[];
  operator: { actor: string; role: OperatorRole };
  actions: WireReviewActions;
}

interface WireReferenceData {
  label: string;
  customer_candidates: Array<{
    reference: string;
    name: string;
    active: boolean;
  }>;
  products_by_line: Array<{
    sku: string;
    description: string | null;
    active: boolean;
    currency: string;
    catalogue_price: string | null;
    available_quantity: string | null;
  } | null>;
}

interface WireCommandResult {
  order_id: string;
  state: OrderState;
  failure_origin: OrderState | null;
  etag: string;
}

interface WireAuditEvent {
  id: string;
  order_id: string;
  event_type: string;
  actor: string;
  occurred_at: string;
  description: string;
}

interface WireAuditList {
  items: WireAuditEvent[];
}

function mapQueueItem(value: WireReviewQueueItem): ReviewQueueItem {
  return {
    id: value.id,
    state: value.state,
    failureOrigin: value.failure_origin,
    customerReference: value.customer_reference,
    poNumber: value.po_number,
    orderDate: value.order_date,
    requestedDeliveryDate: value.requested_delivery_date,
    currency: value.currency,
    createdAt: value.created_at,
    validationIssueCount: value.validation_issue_count,
    highValueApprovalRequired: value.high_value_approval_required,
  };
}

function mapQueuePage(value: WireReviewQueuePage): ReviewQueuePage {
  return {
    items: value.items.map(mapQueueItem),
    states: value.states,
    limit: value.limit,
    offset: value.offset,
    total: value.total,
  };
}

function mapReviewLine(value: WireReviewLine): ReviewLine {
  return {
    sku: value.sku,
    description: value.description,
    quantity: value.quantity,
    submittedPrice: value.submitted_price,
  };
}

function mapDraftToWire(value: ReviewDraft): WireReviewDraftRequest {
  return {
    customer_name: value.customerName,
    customer_reference: value.customerReference,
    po_number: value.poNumber,
    order_date: value.orderDate,
    requested_delivery_date: value.requestedDeliveryDate,
    currency: value.currency,
    lines: value.lines.map((line) => ({
      sku: line.sku,
      description: line.description,
      quantity: line.quantity,
      submitted_price: line.submittedPrice,
    })),
  };
}

function mapRevision(value: WireReviewRevision): ReviewRevision {
  return {
    id: value.id,
    revisionNumber: value.revision_number,
    actor: value.actor,
    createdAt: value.created_at,
    changes: value.changes.map((change) => ({
      fieldPath: change.field_path,
      oldValue: change.old_value,
      newValue: change.new_value,
    })),
  };
}

function mapReviewDetail(value: WireReviewDetail): ReviewDetail {
  const effective = value.effective_draft;
  const extraction = value.original_extraction;
  return {
    etag: value.etag,
    order: {
      id: value.order.id,
      state: value.order.state,
      failureOrigin: value.order.failure_origin,
      createdAt: value.order.created_at,
      customerReference: value.order.customer_reference,
      poNumber: value.order.po_number,
      orderDate: value.order.order_date,
      requestedDeliveryDate: value.order.requested_delivery_date,
      currency: value.order.currency,
      lines: value.order.lines.map((line) => ({
        id: line.id,
        sku: line.sku,
        description: line.description,
        quantity: line.quantity,
        submittedPrice: line.submitted_price,
        trustedCataloguePrice: line.trusted_catalogue_price,
      })),
    },
    sourceDocuments: value.source_documents.map((document) => ({
      id: document.id,
      documentType: document.document_type,
      name: document.name,
      mimeType: document.mime_type,
      sha256: document.sha256,
      messageId: document.message_id,
      storageReference: document.storage_reference,
      metadata: document.metadata.map((pair) => ({ key: pair.key, value: pair.value })),
    })),
    sourceSnapshot: value.source_snapshot === null ? null : {
      id: value.source_snapshot.id,
      sourceDocumentId: value.source_snapshot.source_document_id,
      sourceSha256: value.source_snapshot.source_sha256,
      sourceDocumentType: value.source_snapshot.source_document_type,
      createdAt: value.source_snapshot.created_at,
    },
    originalExtraction: extraction === null ? null : {
      sourceSha256: extraction.source_sha256,
      sourceDocumentType: extraction.source_document_type,
      customerName: extraction.customer_name,
      customerReference: extraction.customer_reference,
      poNumber: extraction.po_number,
      orderDate: extraction.order_date,
      requestedDeliveryDate: extraction.requested_delivery_date,
      currency: extraction.currency,
      lines: extraction.lines.map(mapReviewLine),
      notes: extraction.notes,
      evidence: extraction.evidence.map((item) => ({
        fieldPath: item.field_path,
        sourceLocation: item.source_location,
        quote: item.quote,
      })),
    },
    effectiveDraft: effective === null ? null : {
      customerName: effective.customer_name,
      customerReference: effective.customer_reference,
      poNumber: effective.po_number,
      orderDate: effective.order_date,
      requestedDeliveryDate: effective.requested_delivery_date,
      currency: effective.currency,
      lines: effective.lines.map(mapReviewLine),
      sourceSnapshotId: effective.source_snapshot_id,
      latestRevisionNumber: effective.latest_revision_number,
    },
    revisions: value.revisions.map(mapRevision),
    latestRevision: value.latest_revision === null ? null : mapRevision(value.latest_revision),
    validationIssues: value.validation_issues.map((issue) => ({
      ruleCode: issue.rule_code,
      severity: issue.severity,
      field: issue.field,
      expected: issue.expected,
      actual: issue.actual,
      explanation: issue.explanation,
    })),
    operator: { actor: value.operator.actor, role: value.operator.role },
    actions: {
      canEdit: value.actions.can_edit,
      canApprove: value.actions.can_approve,
      canReject: value.actions.can_reject,
      canRetry: value.actions.can_retry,
    },
  };
}

function mapReferenceData(value: WireReferenceData): ReferenceData {
  return {
    label: value.label,
    customerCandidates: value.customer_candidates.map((customer) => ({
      reference: customer.reference,
      name: customer.name,
      active: customer.active,
    })),
    productsByLine: value.products_by_line.map((product) => product === null ? null : ({
      sku: product.sku,
      description: product.description,
      active: product.active,
      currency: product.currency,
      cataloguePrice: product.catalogue_price,
      availableQuantity: product.available_quantity,
    })),
  };
}

function mapCommandResult(value: WireCommandResult): ReviewCommandResult {
  return {
    orderId: value.order_id,
    state: value.state,
    failureOrigin: value.failure_origin,
    etag: value.etag,
  };
}

function mapAuditEvent(value: WireAuditEvent): AuditEvent {
  return {
    id: value.id,
    orderId: value.order_id,
    eventType: value.event_type,
    actor: value.actor,
    occurredAt: value.occurred_at,
    description: value.description,
  };
}

function mapAuditList(value: WireAuditList): AuditEvent[] {
  return value.items.map(mapAuditEvent);
}

function safeApiError(status: number, body: unknown): ReviewApiError {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "object" && detail !== null && "code" in detail && "message" in detail) {
      const { code, message } = detail;
      if (
        typeof code === "string" && /^[A-Z0-9_]{1,80}$/.test(code)
        && typeof message === "string" && message.trim().length > 0 && message.length <= 500
      ) {
        return new ReviewApiError(status, code, message);
      }
    }
  }
  return new ReviewApiError(status, "API_ERROR", "The review request failed.");
}

async function request(
  fetchImpl: typeof fetch,
  credential: string,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${credential}`);
  try {
    const response = await fetchImpl(path, { ...init, headers });
    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      throw safeApiError(response.status, body);
    }
    return response;
  } catch (error) {
    if (error instanceof ReviewApiError) throw error;
    throw new ReviewApiError(0, "NETWORK_ERROR", "The review service could not be reached.");
  }
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ReviewApiError(response.status, "INVALID_RESPONSE", "The review service returned an invalid response.");
  }
}

function verifyEtagHeader(response: Response, bodyEtag: string): void {
  if (response.headers.get("ETag") !== bodyEtag) {
    throw new ReviewApiError(response.status, "INVALID_RESPONSE", "The review response validator is inconsistent.");
  }
}

export function createReviewApiClient(
  session: OperatorSession,
  fetchImpl: typeof fetch = fetch,
): ReviewApiClient {
  const credential = session.credential;

  return {
    async listOrders(query) {
      const params = new URLSearchParams();
      query.states.forEach((state) => params.append("states", state));
      params.set("limit", String(query.limit));
      params.set("offset", String(query.offset));
      const response = await request(fetchImpl, credential, `/v1/review/orders?${params.toString()}`);
      return mapQueuePage(await responseJson(response) as WireReviewQueuePage);
    },

    async getDetail(orderId) {
      const response = await request(fetchImpl, credential, `/v1/review/orders/${encodeURIComponent(orderId)}`);
      const detail = mapReviewDetail(await responseJson(response) as WireReviewDetail);
      verifyEtagHeader(response, detail.etag);
      return detail;
    },

    async getReferenceData(orderId) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/review/orders/${encodeURIComponent(orderId)}/reference-data`,
      );
      return mapReferenceData(await responseJson(response) as WireReferenceData);
    },

    async saveDraft(orderId, draft, etag) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/review/orders/${encodeURIComponent(orderId)}/draft`,
        {
          method: "PUT",
          headers: { "If-Match": etag, "Content-Type": "application/json" },
          body: JSON.stringify(mapDraftToWire(draft)),
        },
      );
      const detail = mapReviewDetail(await responseJson(response) as WireReviewDetail);
      verifyEtagHeader(response, detail.etag);
      return detail;
    },

    async approve(orderId, etag) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/review/orders/${encodeURIComponent(orderId)}/approve`,
        { method: "POST", headers: { "If-Match": etag } },
      );
      const result = mapCommandResult(await responseJson(response) as WireCommandResult);
      verifyEtagHeader(response, result.etag);
      return result;
    },

    async reject(orderId, reason, etag) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/review/orders/${encodeURIComponent(orderId)}/reject`,
        {
          method: "POST",
          headers: { "If-Match": etag, "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        },
      );
      const result = mapCommandResult(await responseJson(response) as WireCommandResult);
      verifyEtagHeader(response, result.etag);
      return result;
    },

    async retry(orderId, etag) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/review/orders/${encodeURIComponent(orderId)}/retry`,
        { method: "POST", headers: { "If-Match": etag } },
      );
      const result = mapCommandResult(await responseJson(response) as WireCommandResult);
      verifyEtagHeader(response, result.etag);
      return result;
    },

    async getAudit(orderId) {
      const response = await request(
        fetchImpl,
        credential,
        `/v1/orders/${encodeURIComponent(orderId)}/audit`,
      );
      return mapAuditList(await responseJson(response) as WireAuditList);
    },
  };
}
