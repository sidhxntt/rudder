import { spawn } from "node:child_process";
import { platform } from "node:os";

type AuthorizationApi = {
  request(method: string, path: string): Promise<unknown>;
};

type TokenResponse = { access_token: string; expires_in?: number };

export type GitHubLoginDependencies = {
  api: AuthorizationApi;
  open?: (url: string) => Promise<void>;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
  writeError?: (message: string) => void;
  timeoutMs?: number;
};

const POLL_INTERVAL_MS = 1_000;
const AUTHORIZATION_TIMEOUT_MS = 5 * 60 * 1_000;

/** Complete the shared browser authorization handoff and return its bearer token. */
export async function completeGitHubLogin({
  api,
  open = openInBrowser,
  wait = sleep,
  now = Date.now,
  writeError = message => console.error(message),
  timeoutMs = AUTHORIZATION_TIMEOUT_MS,
}: GitHubLoginDependencies): Promise<TokenResponse> {
  const started = await api.request("POST", "/auth/authorizations");
  if (!isAuthorizationStart(started)) {
    throw new Error("Control plane did not return a valid GitHub authorization URL.");
  }

  try {
    await open(started.authorization_url);
  } catch {
    writeError(`Unable to open a browser. Copy and open this URL:\n${started.authorization_url}`);
  }

  const deadline = now() + timeoutMs;
  while (now() < deadline) {
    const consumed = await api.request("POST", `/auth/authorizations/${encodeURIComponent(started.id)}/consume`);
    if (isTokenResponse(consumed)) return consumed;
    if (consumed !== null) throw new Error("Control plane returned an invalid GitHub authorization result.");
    await wait(POLL_INTERVAL_MS);
  }
  throw new Error("GitHub sign-in timed out after five minutes. Run `rudder login` to try again.");
}

async function openInBrowser(url: string): Promise<void> {
  const command = platform() === "darwin" ? "open" : platform() === "win32" ? "cmd" : "xdg-open";
  const args = platform() === "win32" ? ["/c", "start", "", url] : [url];
  await new Promise<void>((resolve, reject) => {
    const child = spawn(command, args, { detached: true, stdio: "ignore" });
    child.once("error", error => { child.unref(); reject(error); });
    child.once("exit", code => {
      child.unref();
      if (code === 0) resolve();
      else reject(new Error(`Browser opener exited with status ${code ?? "unknown"}.`));
    });
  });
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function isAuthorizationStart(value: unknown): value is { id: string; authorization_url: string } {
  return isRecord(value) && typeof value.id === "string" && typeof value.authorization_url === "string";
}

function isTokenResponse(value: unknown): value is TokenResponse {
  return isRecord(value) && typeof value.access_token === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
