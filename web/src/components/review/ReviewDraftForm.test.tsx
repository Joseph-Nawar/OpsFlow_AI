import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReviewApiClient, ReviewDetail, ReviewDraft } from "../../api/review";
import { ReviewApiError } from "../../api/review";
import ReviewDraftForm from "./ReviewDraftForm";

const draft: ReviewDraft = {
  customerName: null,
  customerReference: "CUST-001",
  poNumber: "PO-204",
  orderDate: "2026-09-18",
  requestedDeliveryDate: null,
  currency: "USD",
  lines: [
    { sku: "SKU-001", description: "Widget", quantity: "2", submittedPrice: "10.00" },
    { sku: "SKU-002", description: "Gadget", quantity: "1", submittedPrice: "25.00" },
  ],
};

const savedDetail = {} as ReviewDetail;

function renderForm(
  saveDraft: ReviewApiClient["saveDraft"] = vi.fn(async () => savedDetail),
  onReload: () => Promise<boolean> = vi.fn(async () => true),
) {
  return render(
    <ReviewDraftForm
      api={{ saveDraft }}
      draft={draft}
      etag={'"review-state-v1-order-001"'}
      onReload={onReload}
      onSaved={vi.fn()}
      orderId="order-001"
    />,
  );
}

describe("ReviewDraftForm", () => {
  it("renders only the editable draft whitelist and preserves null inputs", () => {
    renderForm();

    expect(screen.getByRole("heading", { name: "Correct untrusted review draft" })).toBeInTheDocument();
    expect(screen.getByLabelText("Customer name")).toHaveValue("");
    expect(screen.getByLabelText("Requested delivery date")).toHaveValue("");
    expect(screen.getByLabelText("Customer reference")).toHaveValue("CUST-001");
    expect(screen.getByLabelText("Line 1 submitted price")).toHaveValue("10.00");
    expect(screen.getByLabelText("Line 1 submitted price")).toHaveAttribute("inputmode", "decimal");
    expect(screen.queryByLabelText("Source SHA-256")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Trusted catalogue price")).not.toBeInTheDocument();
    expect(screen.queryByText("Validation issues")).not.toBeInTheDocument();
  });

  it("submits the complete candidate draft once with the current ETag and exact strings", async () => {
    const saveDraft = vi.fn(async () => savedDetail);
    const user = userEvent.setup();
    renderForm(saveDraft);

    await user.clear(screen.getByLabelText("Customer name"));
    await user.type(screen.getByLabelText("Customer name"), "  New Customer  ");
    await user.clear(screen.getByLabelText("Line 1 submitted price"));
    await user.type(screen.getByLabelText("Line 1 submitted price"), " 7.50 ");
    await user.click(screen.getByRole("button", { name: "Save & revalidate" }));

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(saveDraft).toHaveBeenCalledWith(
      "order-001",
      {
        ...draft,
        customerName: "  New Customer  ",
        lines: [
          { ...draft.lines[0], submittedPrice: " 7.50 " },
          draft.lines[1],
        ],
      },
      '"review-state-v1-order-001"',
    );
  });

  it("adds, removes, and reorders complete ordered lines", async () => {
    const saveDraft = vi.fn(async () => savedDetail);
    const user = userEvent.setup();
    renderForm(saveDraft);

    await user.click(screen.getByRole("button", { name: "Add line" }));
    expect(screen.getByLabelText("Line 3 SKU")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Remove line 3" }));
    expect(screen.queryByLabelText("Line 3 SKU")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Move line 2 up" }));
    expect(screen.getByLabelText("Line 1 SKU")).toHaveValue("SKU-002");
    expect(screen.getByLabelText("Line 2 SKU")).toHaveValue("SKU-001");

    await user.click(screen.getByRole("button", { name: "Save & revalidate" }));

    expect(saveDraft).toHaveBeenCalledWith(
      "order-001",
      {
        ...draft,
        lines: [draft.lines[1], draft.lines[0]],
      },
      '"review-state-v1-order-001"',
    );
  });

  it("blocks duplicate submission while Save & revalidate is pending", async () => {
    let resolveSave!: (value: ReviewDetail) => void;
    const saveDraft = vi.fn(() => new Promise<ReviewDetail>((resolve) => { resolveSave = resolve; }));
    const user = userEvent.setup();
    renderForm(saveDraft);

    const submit = screen.getByRole("button", { name: "Save & revalidate" });
    await user.click(submit);
    await user.click(submit);

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(submit).toBeDisabled();
    resolveSave(savedDetail);
  });

  it("shows bounded no-op feedback and leaves the form usable", async () => {
    const saveDraft = vi.fn(async () => {
      throw new ReviewApiError(409, "NO_REVIEW_CHANGES", "No review changes were submitted.");
    });
    const user = userEvent.setup();
    renderForm(saveDraft);

    await user.click(screen.getByRole("button", { name: "Save & revalidate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No review changes were submitted.");
    expect(screen.getByLabelText("Customer reference")).toHaveValue("CUST-001");
  });

  it("uses a fixed safe message for unknown failures and leaves the draft usable", async () => {
    const saveDraft = vi.fn(async () => {
      throw new Error("raw provider response or credential");
    });
    const user = userEvent.setup();
    renderForm(saveDraft);

    await user.click(screen.getByRole("button", { name: "Save & revalidate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to save and revalidate this review case. Please try again.",
    );
    expect(screen.queryByText("raw provider response or credential")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Customer reference")).toHaveValue("CUST-001");
  });

  it("handles stale 412 only with explicit reload and never replays the save", async () => {
    const saveDraft = vi.fn(async () => {
      throw new ReviewApiError(412, "PRECONDITION_FAILED", "The review case changed; reload it.");
    });
    const onReload = vi.fn(async () => true);
    const user = userEvent.setup();
    renderForm(saveDraft, onReload);

    await user.click(screen.getByRole("button", { name: "Save & revalidate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This review case changed and must be reloaded.");
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(onReload).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reload review case" }));

    expect(onReload).toHaveBeenCalledTimes(1);
    expect(saveDraft).toHaveBeenCalledTimes(1);
  });
});
