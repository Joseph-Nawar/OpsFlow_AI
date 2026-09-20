import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import ReviewRouter from "./Router";

describe("review route shell", () => {
  it("renders the queue shell only at /review", () => {
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <ReviewRouter />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review case" })).not.toBeInTheDocument();
  });

  it("renders the detail shell with the route order id", () => {
    render(
      <MemoryRouter initialEntries={["/review/order-123"]}>
        <ReviewRouter />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Review case" })).toBeInTheDocument();
    expect(screen.getByText("order-123")).toBeInTheDocument();
  });

  it("does not introduce additional review routes", () => {
    render(
      <MemoryRouter initialEntries={["/review/order-123/actions"]}>
        <ReviewRouter />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("heading", { name: "Review queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review case" })).not.toBeInTheDocument();
  });
});
