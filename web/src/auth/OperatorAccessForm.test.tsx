import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import OperatorAccessForm from "./OperatorAccessForm";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("OperatorAccessForm", () => {
  it("accepts a credential only after a protected queue request succeeds", async () => {
    const protectedFetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], states: [], limit: 1, offset: 0, total: 0 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", protectedFetch);
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();
    render(<OperatorAccessForm onAuthenticated={onAuthenticated} />);

    await user.type(screen.getByLabelText("Development bearer credential"), "test-only-review-credential");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith({ credential: "test-only-review-credential" }));
    expect(protectedFetch).toHaveBeenCalledOnce();
    expect(protectedFetch.mock.calls[0]?.[0]).toContain("/v1/review/orders?");
    expect(new Headers(protectedFetch.mock.calls[0]?.[1]?.headers).get("Authorization"))
      .toBe("Bearer test-only-review-credential");
    expect(sessionStorage.length).toBe(1);
    expect(screen.queryByText(/reviewer-demo|APPROVER|REVIEWER/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/actor|role/i)).not.toBeInTheDocument();
  });

  it("shows safe authentication feedback and does not store a rejected credential", async () => {
    const rejectedFetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: "AUTHENTICATION_REQUIRED", message: "A configured bearer credential is required." } }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", rejectedFetch);
    const onAuthenticated = vi.fn();
    render(<OperatorAccessForm onAuthenticated={onAuthenticated} />);

    fireEvent.change(screen.getByLabelText("Development bearer credential"), {
      target: { value: "rejected-test-credential" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/authentication failed/i);
    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
    expect(screen.getByLabelText("Development bearer credential")).toHaveValue("rejected-test-credential");
  });

  it("does not treat a session-restored credential as authenticated until the protected request succeeds", async () => {
    sessionStorage.setItem("opsflow.review.developmentCredential", "restored-test-credential");
    const protectedFetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], states: [], limit: 1, offset: 0, total: 0 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", protectedFetch);
    const onAuthenticated = vi.fn();
    render(<OperatorAccessForm onAuthenticated={onAuthenticated} />);

    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(protectedFetch).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Development bearer credential")).toHaveValue("restored-test-credential");

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith({ credential: "restored-test-credential" }));
    expect(protectedFetch).toHaveBeenCalledOnce();
  });
});
