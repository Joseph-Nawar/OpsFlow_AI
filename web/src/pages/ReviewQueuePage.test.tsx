import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type {
  ReviewApiClient,
  ReviewApiError,
  ReviewQueueItem,
  ReviewQueuePage as ReviewQueuePageModel,
  ReviewState,
} from "../api/review";
import ReviewQueuePage from "./ReviewQueuePage";

const DEFAULT_STATES: ReviewState[] = [
  "NEEDS_REVIEW",
  "READY_FOR_APPROVAL",
  "FAILED_RETRYABLE",
];

function queueItem(overrides: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
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
    highValueApprovalRequired: true,
    ...overrides,
  };
}

function queuePage(
  items: ReviewQueueItem[] = [queueItem()],
  overrides: Partial<ReviewQueuePageModel> = {},
): ReviewQueuePageModel {
  return {
    items,
    states: DEFAULT_STATES,
    limit: 50,
    offset: 0,
    total: items.length,
    ...overrides,
  };
}

function apiDouble(
  listOrders: ReviewApiClient["listOrders"],
): Pick<ReviewApiClient, "listOrders"> {
  return { listOrders };
}

function renderQueue(element: ReactElement) {
  return render(<MemoryRouter>{element}</MemoryRouter>);
}

describe("ReviewQueuePage", () => {
  it("shows loading while the initial queue request is pending", () => {
    let resolveRequest!: (value: ReviewQueuePageModel) => void;
    const request = new Promise<ReviewQueuePageModel>((resolve) => {
      resolveRequest = resolve;
    });
    const api = apiDouble(vi.fn(() => request));

    renderQueue(<ReviewQueuePage api={api} />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading review queue");
    resolveRequest(queuePage());
  });

  it("requests the default states and renders queue business values", async () => {
    const api = apiDouble(vi.fn(async () => queuePage([
      queueItem(),
      queueItem({
        id: "order-002",
        state: "READY_FOR_APPROVAL",
        customerReference: null,
        poNumber: null,
        orderDate: null,
        createdAt: "2026-09-20T10:15:00Z",
        validationIssueCount: 0,
        highValueApprovalRequired: false,
      }),
    ], { total: 2 })));

    renderQueue(<ReviewQueuePage api={api} />);

    expect(await screen.findByText("CUST-001")).toBeInTheDocument();
    expect(api.listOrders).toHaveBeenCalledWith({
      states: DEFAULT_STATES,
      limit: 50,
      offset: 0,
    });
    expect(screen.getByText("PO-204")).toBeInTheDocument();
    expect(screen.getByText("Order date: 2026-09-18")).toBeInTheDocument();
    expect(screen.getByText("Created: 2026-09-20T10:15:00Z")).toBeInTheDocument();
    expect(screen.getByText("2 validation issues")).toBeInTheDocument();
    expect(screen.getByText("High-value approval required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open order-001" })).toHaveAttribute(
      "href",
      "/review/order-001",
    );
  });

  it("renders a clear empty state", async () => {
    const api = apiDouble(vi.fn(async () => queuePage([], { total: 0 })));

    renderQueue(<ReviewQueuePage api={api} />);

    expect(await screen.findByText("No review orders match the selected states.")).toBeInTheDocument();
  });

  it("renders a bounded safe error and retry control", async () => {
    const api = apiDouble(vi.fn(async () => {
      throw new Error("provider payload must not be shown");
    }));

    renderQueue(<ReviewQueuePage api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load the review queue. Please try again.",
    );
    expect(screen.queryByText("provider payload must not be shown")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("keeps one filter selected and resets offset when filters change", async () => {
    const api = apiDouble(vi.fn(async ({ states, offset }) => queuePage([], {
      states,
      offset,
      total: 101,
    })));
    const user = userEvent.setup();

    renderQueue(<ReviewQueuePage api={api} />);
    await screen.findByText("No review orders match the selected states.");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(api.listOrders).toHaveBeenLastCalledWith({
      states: DEFAULT_STATES,
      limit: 50,
      offset: 50,
    }));

    await user.click(screen.getByRole("checkbox", { name: "NEEDS_REVIEW" }));
    await waitFor(() => expect(api.listOrders).toHaveBeenLastCalledWith({
      states: ["READY_FOR_APPROVAL", "FAILED_RETRYABLE"],
      limit: 50,
      offset: 0,
    }));

    await user.click(screen.getByRole("checkbox", { name: "READY_FOR_APPROVAL" }));
    expect(screen.getByRole("checkbox", { name: "FAILED_RETRYABLE" })).toBeDisabled();
  });

  it("bounds previous and next pagination from the backend total", async () => {
    const api = apiDouble(vi.fn(async ({ offset, states }) => queuePage([], {
      states,
      offset,
      total: 101,
    })));
    const user = userEvent.setup();

    renderQueue(<ReviewQueuePage api={api} />);
    await screen.findByText("No review orders match the selected states.");

    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(api.listOrders).toHaveBeenLastCalledWith({
      states: DEFAULT_STATES,
      limit: 50,
      offset: 50,
    }));
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(api.listOrders).toHaveBeenLastCalledWith({
      states: DEFAULT_STATES,
      limit: 50,
      offset: 100,
    }));
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() => expect(api.listOrders).toHaveBeenLastCalledWith({
      states: DEFAULT_STATES,
      limit: 50,
      offset: 50,
    }));
  });

  it("renders unknown runtime states as a bounded safe label", async () => {
    const unknownItem = queueItem({ state: "FUTURE_SERVER_STATE" as ReviewState });
    const api = apiDouble(vi.fn(async () => queuePage([unknownItem])));

    renderQueue(<ReviewQueuePage api={api} />);

    expect(await screen.findByText("Unknown state")).toBeInTheDocument();
  });

  it("navigates to the order detail route using React Router", async () => {
    const api = apiDouble(vi.fn(async () => queuePage()));
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/review"]}>
        <Routes>
          <Route element={<ReviewQueuePage api={api} />} path="/review" />
          <Route element={<p>Detail placeholder</p>} path="/review/:orderId" />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("link", { name: "Open order-001" }));

    expect(screen.getByText("Detail placeholder")).toBeInTheDocument();
  });

  it("does not expose raw ReviewApiError details in the queue error", async () => {
    const api = apiDouble(vi.fn(async () => {
      throw new (class extends Error implements Partial<ReviewApiError> {
        status = 503;
        code = "PROVIDER_SECRET";
        message = "secret provider response";
      })();
    }));

    render(<ReviewQueuePage api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load the review queue");
    expect(screen.queryByText("secret provider response")).not.toBeInTheDocument();
  });
});
