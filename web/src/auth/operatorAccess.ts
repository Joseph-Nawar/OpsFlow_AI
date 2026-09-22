const OPERATOR_CREDENTIAL_KEY = "opsflow.review.developmentCredential";

export function readOperatorCredential(): string {
  return window.sessionStorage.getItem(OPERATOR_CREDENTIAL_KEY) ?? "";
}

export function storeOperatorCredential(credential: string): void {
  if (credential.length === 0) {
    clearOperatorCredential();
    return;
  }
  window.sessionStorage.setItem(OPERATOR_CREDENTIAL_KEY, credential);
}

export function clearOperatorCredential(): void {
  window.sessionStorage.removeItem(OPERATOR_CREDENTIAL_KEY);
}
