import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReferenceData, ReviewApiClient } from "../../api/review";
import ReviewReferencePanel from "./ReviewReferencePanel";

const referenceData: ReferenceData = {
  label: "Current trusted reference data",
  customerCandidates: [
    { reference: "CUST-001", name: "Acme Industries", active: true },
    { reference: "CUST-003", name: "Inactive Industries", active: false },
  ],
  productsByLine: [
    {
      sku: "SKU-001",
      description: "Widget",
      active: true,
      currency: "USD",
      cataloguePrice: "10.00",
      availableQuantity: "100",
    },
    null,
  ],
};

function apiDouble(
  getReferenceData: ReviewApiClient["getReferenceData"],
): Pick<ReviewApiClient, "getReferenceData"> {
  return { getReferenceData };
}

describe("ReviewReferencePanel", () => {
  it("loads and labels current trusted reference data independently", async () => {
    const api = apiDouble(vi.fn(async () => referenceData));

    render(<ReviewReferencePanel api={api} orderId="order-001" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading current trusted reference data");
    expect(await screen.findByRole("heading", { name: "Current trusted reference data" })).toBeInTheDocument();
    expect(api.getReferenceData).toHaveBeenCalledWith("order-001");
    expect(screen.getByText("CUST-001 — Acme Industries (active)")).toBeInTheDocument();
    expect(screen.getByText("CUST-003 — Inactive Industries (inactive)")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").some((item) => item.textContent?.includes("SKU-001"))).toBe(true);
    expect(screen.getByText("Line 2: No exact trusted product found.")).toBeInTheDocument();
  });

  it("renders unavailable reference data safely and retries independently", async () => {
    const api = apiDouble(vi.fn()
      .mockRejectedValueOnce(new Error("raw provider response"))
      .mockResolvedValueOnce(referenceData));
    const user = userEvent.setup();

    render(<ReviewReferencePanel api={api} orderId="order-001" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Current trusted reference data is unavailable. Please try again.",
    );
    expect(screen.queryByText("raw provider response")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry reference data" }));

    await waitFor(() => expect(api.getReferenceData).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      expect(screen.getAllByRole("listitem").some((item) => item.textContent?.includes("SKU-001"))).toBe(true);
    });
  });
});
