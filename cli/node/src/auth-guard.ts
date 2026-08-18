export type AuthenticationGate = "ready" | "interactive-login" | "noninteractive-error";

/** Decide whether an operator command can reach the shared control-plane API. */
export function authenticationGate({
  hasToken,
  noInteractive,
  isTTY,
}: {
  hasToken: boolean;
  noInteractive: boolean;
  isTTY: boolean;
}): AuthenticationGate {
  if (hasToken) return "ready";
  return noInteractive || !isTTY ? "noninteractive-error" : "interactive-login";
}
