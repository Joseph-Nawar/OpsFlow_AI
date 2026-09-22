import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { clearOperatorCredential } from "./auth/operatorAccess";
import {
  auditListWireFixture,
  queueWireFixture,
  referenceDataWireFixture,
  reviewDetailWireFixture,
} from "./test/fixtures";

function jsonResponse(body: unknown, etag?: string): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ...(etag === undefined ? {} : { ETag: etag }) },
  });
}

describe("full application credential switching", () => {
  beforeEach(() => {
    clearOperatorCredential();
    window.history.pushState({}, "", "/review/order-001");
  });

  afterEach(() => {
    clearOperatorCredential();
    vi.unstubAllGlobals();
  });

  it("re-verifies a second credential and replaces server-resolved identity/actions", async () => {
    const reviewerDetail = {
      ...reviewDetailWireFixture,
      operator: { actor: "reviewer-demo", role: "REVIEWER" },
      actions: { can_edit: true, can_approve: false, can_reject: true, can_retry: false },
    };
    const approverDetail = {
      ...reviewDetailWireFixture,
      etag: '"review-state-v1-approver"',
      operator: { actor: "approver-demo", role: "APPROVER" },
      actions: { can_edit: false, can_approve: true, can_reject: true, can_retry: false },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const authorization = new Headers(init?.headers).get("Authorization");
      const detail = authorization === "Bearer approver-test-credential" ? approverDetail : reviewerDetail;
      if (url.includes("/reference-data")) return jsonResponse(referenceDataWireFixture);
      if (url.includes("/audit")) return jsonResponse(auditListWireFixture);
      if (url.includes("/v1/review/orders/order-001")) return jsonResponse(detail, detail.etag);
      return jsonResponse(queueWireFixture);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText("Development bearer credential"), "reviewer-test-credential");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Operator: reviewer-demo (REVIEWER)")).toBeInTheDocument();
    expect(screen.getByText("Can approve: No")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await user.type(screen.getByLabelText("Development bearer credential"), "approver-test-credential");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText("Operator: approver-demo (APPROVER)")).toBeInTheDocument();
    expect(screen.getByText("Can approve: Yes")).toBeInTheDocument();
    expect(screen.queryByText("Operator: reviewer-demo (REVIEWER)")).not.toBeInTheDocument();

    const detailRequests = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/v1/review/orders/order-001"));
    expect(detailRequests).toHaveLength(2);
    expect(new Headers(detailRequests[0][1]?.headers).get("Authorization")).toBe("Bearer reviewer-test-credential");
    expect(new Headers(detailRequests[1][1]?.headers).get("Authorization")).toBe("Bearer approver-test-credential");
  });
});
