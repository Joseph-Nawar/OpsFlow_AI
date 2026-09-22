import { beforeEach, describe, expect, it } from "vitest";

import {
  clearOperatorCredential,
  readOperatorCredential,
  storeOperatorCredential,
} from "./operatorAccess";

describe("development operator credential storage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("stores and reads only the session-scoped credential", () => {
    storeOperatorCredential("test-only-review-credential");

    expect(readOperatorCredential()).toBe("test-only-review-credential");
    expect(sessionStorage.length).toBe(1);
    expect(localStorage.length).toBe(0);
  });

  it("clears a credential on sign-out", () => {
    storeOperatorCredential("test-only-review-credential");

    clearOperatorCredential();

    expect(readOperatorCredential()).toBe("");
    expect(sessionStorage.length).toBe(0);
    expect(localStorage.length).toBe(0);
  });
});
