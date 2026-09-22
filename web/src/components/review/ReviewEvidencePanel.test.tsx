import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OriginalExtraction, SourceDocument, SourceSnapshot } from "../../api/review";
import ReviewEvidencePanel from "./ReviewEvidencePanel";

const sourceDocument: SourceDocument = {
  id: "source-001",
  documentType: "EMAIL",
  name: "purchase-order.eml",
  mimeType: "message/rfc822",
  sha256: "a".repeat(64),
  messageId: "message-001",
  storageReference: "mailbox/message-001",
  metadata: [
    { key: "sender", value: "buyer@example.invalid" },
    { key: "received", value: "2026-09-19T08:30:00Z" },
  ],
};

const sourceSnapshot: SourceSnapshot = {
  id: "snapshot-001",
  sourceDocumentId: "source-001",
  sourceSha256: "a".repeat(64),
  sourceDocumentType: "EMAIL",
  createdAt: "2026-09-19T08:30:01Z",
};

const originalExtraction: OriginalExtraction = {
  sourceSha256: "a".repeat(64),
  sourceDocumentType: "EMAIL",
  customerName: "Acme Industries",
  customerReference: "CUST-001",
  poNumber: "PO-204",
  orderDate: "2026-09-18",
  requestedDeliveryDate: null,
  currency: "USD",
  lines: [{ sku: "SKU-001", description: "Widget", quantity: "2", submittedPrice: "10.00" }],
  notes: "Original extraction note",
  evidence: [
    { fieldPath: "po_number", sourceLocation: "page 1, line 4", quote: "PO-204" },
    { fieldPath: "customer_reference", sourceLocation: null, quote: null },
  ],
};

describe("ReviewEvidencePanel", () => {
  it("labels and renders original AI provenance, source metadata, snapshot, and evidence", () => {
    render(
      <ReviewEvidencePanel
        originalExtraction={originalExtraction}
        sourceDocuments={[sourceDocument]}
        sourceSnapshot={sourceSnapshot}
      />,
    );

    expect(screen.getByRole("heading", { name: "ORIGINAL AI extraction / provenance" })).toBeInTheDocument();
    expect(screen.getByText("purchase-order.eml")).toBeInTheDocument();
    expect(screen.getByText("message/rfc822")).toBeInTheDocument();
    expect(screen.getByText("mailbox/message-001")).toBeInTheDocument();
    expect(screen.getByText("snapshot-001")).toBeInTheDocument();
    expect(screen.getByText("Acme Industries")).toBeInTheDocument();
    expect(screen.getByText("Original extraction note")).toBeInTheDocument();
    expect(screen.getByText("page 1, line 4")).toBeInTheDocument();
    expect(screen.getAllByText("PO-204")).toHaveLength(2);
    expect(screen.getByText(/Evidence does not prove a later human edit/)).toBeInTheDocument();
    expect(screen.getByText("Raw source files are not persisted or viewable in Phase 6.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    const metadata = screen.getByRole("list", { name: "Source metadata" });
    expect(within(metadata).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "sender: buyer@example.invalid",
      "received: 2026-09-19T08:30:00Z",
    ]);
  });

  it("keeps nullable source and evidence values safe and explicit", () => {
    render(
      <ReviewEvidencePanel
        originalExtraction={{ ...originalExtraction, evidence: [{ fieldPath: "currency", sourceLocation: null, quote: null }] }}
        sourceDocuments={[]}
        sourceSnapshot={null}
      />,
    );

    expect(screen.getByText("No source snapshot is available.")).toBeInTheDocument();
    expect(screen.getByText("No source documents are available.")).toBeInTheDocument();
    expect(screen.getByText("No source location provided")).toBeInTheDocument();
    expect(screen.getByText("No quote provided")).toBeInTheDocument();
  });

  it("does not imply that missing extraction data can be reconstructed", () => {
    render(
      <ReviewEvidencePanel
        originalExtraction={null}
        sourceDocuments={[]}
        sourceSnapshot={null}
      />,
    );

    expect(screen.getByText("No original AI extraction is available for this review case.")).toBeInTheDocument();
  });
});
