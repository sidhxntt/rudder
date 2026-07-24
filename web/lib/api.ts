/**
 * THE SEAM.
 *
 * Every byte of data the UI touches passes through this module, and it is the
 * only place in `web/` that calls `fetch`. Every function below is checked
 * against the live OpenAPI document; the exact REST call is written above it.
 *
 * ## Why `/api` and not `http://localhost:8000`
 *
 * The control plane mounts no CORS middleware, so a browser request from
 * :3000 straight to :8000 is cross-origin and the response is unreadable —
 * ports are not part of a *site* (which is why the `SameSite=Lax` cookie is
 * fine) but they very much are part of an *origin*. Every call therefore goes
 * to this app's own origin under `/api`, and `next.config.ts` rewrites that to
 * the control plane. Same-origin means the `rudder_token` cookie rides along
 * with no preflight, no `Access-Control-Allow-Credentials`, and no JWT in
 * `localStorage`.
 */

import type {
  Deployment,
  Domain,
  GitHubImportStatus,
  GitHubImport,
  GitHubImportConfirmation,
  GitHubImportPreview,
  GitHubInstallation,
  GitHubRepository,
  Environment,
  Instance,
  Project,
  Service,
  ServiceUpdate,
  TokenResponse,
  User,
  Variable,
} from "./types";

/** Same-origin prefix. `next.config.ts` rewrites it onto the control plane. */
const BASE = "/api";

/**
 * The uniform error shape from the PRD's API design rules, carried as an
 * exception. `status` is kept because the UI reacts to 401 (log in again) and
 * 404 (a deployment with no build log) differently from everything else.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | undefined;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Two error bodies exist in the wild: the PRD's `{code, message, details}`
 * envelope from the resource routers, and FastAPI's own `{detail}` from the
 * handful of places that raise a bare `HTTPException` (the build-log 404).
 */
async function toApiError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || `request failed with status ${response.status}`;
  let details: Record<string, unknown> | undefined;

  try {
    const body: unknown = await response.json();
    if (isRecord(body)) {
      if (typeof body.code === "string" && typeof body.message === "string") {
        code = body.code;
        message = body.message;
        if (isRecord(body.details)) details = body.details;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      }
    }
  } catch {
    // Non-JSON body (an HTML error page from a proxy, an empty 502). The
    // status-derived message above is the best available.
  }

  return new ApiError(response.status, code, message, details);
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    // Same-origin thanks to the rewrite, so this is all the cookie needs.
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) throw await toApiError(response);
  return response;
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  return (await response.json()) as T;
}

async function requestEmpty(path: string, options: RequestOptions = {}): Promise<void> {
  const response = await send(path, options);
  // 204 has no body; nothing to read and nothing to return.
  if (response.status !== 204) await response.text();
}

const id = encodeURIComponent;

// --- Auth -----------------------------------------------------------------

/**
 * POST /auth/token
 *
 * Returns the bearer token for header clients *and* sets an httpOnly
 * `rudder_token` cookie. The browser uses the cookie: the response body is
 * consumed and dropped on purpose, because storing the JWT anywhere JavaScript
 * can reach it is exactly what the cookie exists to avoid.
 */
export async function login(email: string, password: string): Promise<void> {
  await requestJson<TokenResponse>("/auth/token", {
    method: "POST",
    body: { email, password },
  });
}

/** DELETE /auth/token → 204. Clears the session cookie. */
export function logout(): Promise<void> {
  return requestEmpty("/auth/token", { method: "DELETE" });
}

/** GET /auth/me → the session check on load. 401 when there is no session. */
export function me(): Promise<User> {
  return requestJson<User>("/auth/me");
}

// --- Resources -------------------------------------------------------------

/** GET /projects */
export function listProjects(): Promise<Project[]> {
  return requestJson<Project[]>("/projects");
}

/** GET /github/import/status — whether the operator configured the GitHub App. */
export function getGitHubImportStatus(): Promise<GitHubImportStatus> {
  return requestJson<GitHubImportStatus>("/github/import/status");
}

/** GET /github/import/installations — GitHub App accounts connected to Rudder. */
export function listGitHubInstallations(): Promise<GitHubInstallation[]> {
  return requestJson<GitHubInstallation[]>("/github/import/installations");
}

/** GET /github/import/repositories?installation_id=... */
export function listGitHubRepositories(installationId: number): Promise<GitHubRepository[]> {
  return requestJson<GitHubRepository[]>(`/github/import/repositories?installation_id=${installationId}`);
}

/** GET /github/import/branches?installation_id=...&repository=... */
export function listGitHubBranches(installationId: number, repository: string): Promise<string[]> {
  return requestJson<string[]>(
    `/github/import/branches?installation_id=${installationId}&repository=${id(repository)}`,
  );
}

export function previewGitHubImport(args: {
  installationId: number;
  repository: string;
  branch: string;
}): Promise<GitHubImportPreview> {
  return requestJson<GitHubImportPreview>("/github/import/preview", {
    method: "POST",
    body: {
      installation_id: args.installationId,
      repository: args.repository,
      branch: args.branch,
    },
  });
}

export function confirmGitHubImport(args: {
  installationId: number;
  repository: string;
  branch: string;
  addons: Array<"postgres" | "redis">;
}): Promise<GitHubImportConfirmation> {
  return requestJson<GitHubImportConfirmation>("/github/imports", {
    method: "POST",
    body: {
      installation_id: args.installationId,
      repository: args.repository,
      branch: args.branch,
      addons: args.addons,
    },
  });
}

export function getGitHubImport(importId: string): Promise<GitHubImport> {
  return requestJson<GitHubImport>(`/github/imports/${id(importId)}`);
}

/** GET /projects/{project_id}/environments */
export function listEnvironments(projectId: string): Promise<Environment[]> {
  return requestJson<Environment[]>(`/projects/${id(projectId)}/environments`);
}

/** GET /environments/{environment_id}/services */
export function listServices(environmentId: string): Promise<Service[]> {
  return requestJson<Service[]>(`/environments/${id(environmentId)}/services`);
}

/** GET /services/{service_id} */
export function getService(serviceId: string): Promise<Service> {
  return requestJson<Service>(`/services/${id(serviceId)}`);
}

/**
 * PATCH /services/{service_id} → the full ServiceRead.
 *
 * The canvas drag persists `canvas_x`/`canvas_y` through here and sends
 * nothing else. Per D6 this is UI metadata: the control plane stores it,
 * nothing reconciles against it, and it triggers no deploy.
 */
export function updateService(serviceId: string, patch: ServiceUpdate): Promise<Service> {
  return requestJson<Service>(`/services/${id(serviceId)}`, {
    method: "PATCH",
    body: patch,
  });
}

/** GET /environments/{environment_id}/domains */
export function listDomains(environmentId: string): Promise<Domain[]> {
  return requestJson<Domain[]>(`/environments/${id(environmentId)}/domains`);
}

/** GET /services/{service_id}/deployments — newest first. */
export function listDeployments(serviceId: string): Promise<Deployment[]> {
  return requestJson<Deployment[]>(`/services/${id(serviceId)}/deployments`);
}

/** GET /services/{service_id}/instances — the running containers. */
export function listInstances(serviceId: string): Promise<Instance[]> {
  return requestJson<Instance[]>(`/services/${id(serviceId)}/instances`);
}

/**
 * POST /services/{service_id}/deploy → 202 with Deployment(status=queued).
 *
 * The body is optional and pins a SHA; the canvas never pins one, so the
 * branch tip is what gets built.
 */
export function createDeployment(serviceId: string): Promise<Deployment> {
  return requestJson<Deployment>(`/services/${id(serviceId)}/deploy`, {
    method: "POST",
    body: {},
  });
}

/** GET /services/{service_id}/variables — values are never in the response. */
export function listVariables(serviceId: string): Promise<Variable[]> {
  return requestJson<Variable[]>(`/services/${id(serviceId)}/variables`);
}

/** PUT /services/{service_id}/variables/{key} — idempotent, value write-only. */
export function putVariable(
  serviceId: string,
  key: string,
  value: string,
): Promise<Variable> {
  return requestJson<Variable>(`/services/${id(serviceId)}/variables/${id(key)}`, {
    method: "PUT",
    body: { value },
  });
}

/** DELETE /services/{service_id}/variables/{key} → 204. */
export function deleteVariable(serviceId: string, key: string): Promise<void> {
  return requestEmpty(`/services/${id(serviceId)}/variables/${id(key)}`, {
    method: "DELETE",
  });
}

// --- Build log stream ------------------------------------------------------

export interface BuildLogHandlers {
  /** One batch of log lines, in order. Batched per network read. */
  onLines: (lines: string[]) => void;
  /** The terminal frame. `outcome` is `succeeded` or `failed`. */
  onEnd: (outcome: string) => void;
}

interface SseFrame {
  event: string | null;
  data: string[];
}

/**
 * Parse one SSE frame (the text between blank lines).
 *
 * Wire format, from `control-plane/rudder_cp/logs/sse.py`:
 *   `data: <line>` repeated — build output
 *   `: keepalive`           — a comment, ignored
 *   `event: end` + `data: succeeded|failed` — terminal
 */
function parseFrame(frame: string): SseFrame {
  let event: string | null = null;
  const data: string[] = [];

  for (const raw of frame.split("\n")) {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (line.length === 0 || line.startsWith(":")) continue; // comment / keepalive
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trimStart();
      continue;
    }
    if (line.startsWith("data:")) {
      const value = line.slice("data:".length);
      // SSE strips exactly one leading space after the colon.
      data.push(value.startsWith(" ") ? value.slice(1) : value);
    }
  }

  return { event, data };
}

/**
 * GET /deployments/{deployment_id}/build-log — SSE.
 *
 * Read with `fetch` rather than `EventSource` for two reasons that both bite in
 * practice: `EventSource` cannot see the response status, so the 404 this
 * endpoint returns for a deployment that never produced a log would look like a
 * transport error and it would reconnect forever; and `EventSource` has no
 * abort, only `close()`, which cannot cancel the in-flight request. An
 * `AbortSignal` covers unmount and the reader is cancelled the moment the
 * terminal frame arrives, so the connection is never held open past the end of
 * the build.
 *
 * Disconnecting cannot affect the build: the server tails a file and the writer
 * is the deploy worker, which never learns a reader left.
 *
 * Resolves when the stream ends. Rejects with `ApiError` (404 for no log) or
 * with the signal's abort reason.
 */
export async function streamBuildLog(
  deploymentId: string,
  handlers: BuildLogHandlers,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/deployments/${id(deploymentId)}/build-log`, {
    method: "GET",
    headers: { Accept: "text/event-stream" },
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });

  if (!response.ok) throw await toApiError(response);
  if (!response.body) {
    throw new ApiError(response.status, "no_stream", "the build log response had no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;

      buffer += decoder.decode(value, { stream: true });

      const lines: string[] = [];
      let outcome: string | null = null;

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);

        if (frame.event === "end") {
          outcome = frame.data.join("");
        } else {
          // The server renders a chunk as one `data:` line per newline, so a
          // chunk ending in a newline yields a trailing empty entry. Drop it
          // rather than paint a blank line after every read.
          while (frame.data.length > 0 && frame.data[frame.data.length - 1] === "") {
            frame.data.pop();
          }
          lines.push(...frame.data);
        }

        if (outcome !== null) break;
        boundary = buffer.indexOf("\n\n");
      }

      if (lines.length > 0) handlers.onLines(lines);
      if (outcome !== null) {
        handlers.onEnd(outcome);
        return;
      }
    }
  } finally {
    // Cancelling closes the connection. On the server that closes the async
    // generator, which closes the file handle; the build is untouched.
    await reader.cancel().catch(() => undefined);
  }
}
