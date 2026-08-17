import { execFile } from "node:child_process";
import { platform } from "node:os";
import { promisify } from "node:util";

import type { ApiClient } from "./client.js";

type Start = { handoff_id: string; authorization_url: string };
type Token = { access_token: string; expires_in: number };

export async function completeGitHubLogin({
  api,
  open = openBrowser,
  wait = (milliseconds: number) => new Promise<void>(resolve => setTimeout(resolve, milliseconds)),
}: {
  api: Pick<ApiClient, "request">;
  open?: (url: string) => void;
  wait?: (milliseconds: number) => Promise<void>;
}): Promise<Token> {
  const started = await api.request("POST", "/auth/github/cli/start") as Start;
  if (!started.handoff_id || !started.authorization_url) throw new Error("Control plane returned an invalid GitHub login handoff.");
  open(started.authorization_url);
  for (let attempt = 0; attempt < 300; attempt++) {
    const token = await api.request("POST", "/auth/github/cli/exchange", { handoff_id: started.handoff_id }) as Token | null;
    if (token?.access_token) return token;
    await wait(1000);
  }
  throw new Error("GitHub login timed out. Run `rudder login` again.");
}

function openBrowser(url: string): void {
  const command = platform() === "darwin" ? "open" : platform() === "win32" ? "cmd" : "xdg-open";
  const args = platform() === "win32" ? ["/c", "start", "", url] : [url];
  void promisify(execFile)(command, args).catch(() => undefined);
}
