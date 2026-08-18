export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly detail?: unknown) { super(message); }
}

export type FetchLike = typeof fetch;

export class ApiClient {
  readonly baseUrl: string;
  constructor(baseUrl: string, private readonly token?: string, private readonly fetcher: FetchLike = fetch) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async request(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetcher(new URL(path, `${this.baseUrl}/`).toString(), {
        method,
        headers: { accept: "application/json", ...(body === undefined ? {} : { "content-type": "application/json" }), ...(this.token ? { authorization: `Bearer ${this.token}` } : {}), ...extraHeaders },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (cause) {
      throw new ApiError(0, `Cannot reach the Rudder control plane at ${this.baseUrl}.`, cause);
    }
    if (response.status === 204) return null;
    const text = await response.text();
    const parsed: unknown = text ? safeJson(text) : null;
    if (!response.ok) {
      const detail = isRecord(parsed) ? parsed.detail : undefined;
      const message = isRecord(detail) && typeof detail.message === "string" ? detail.message
        : isRecord(parsed) && typeof parsed.message === "string" ? parsed.message
        : typeof detail === "string" ? detail : `API returned HTTP ${response.status}`;
      throw new ApiError(response.status, message, parsed);
    }
    return parsed;
  }

  async *stream(path: string): AsyncGenerator<string> {
    const response = await this.fetcher(new URL(path, `${this.baseUrl}/`).toString(), { headers: { accept: "text/event-stream", ...(this.token ? { authorization: `Bearer ${this.token}` } : {}) } });
    if (!response.ok || !response.body) throw new ApiError(response.status, `API returned HTTP ${response.status}`);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buffer += value;
      const entries = buffer.split("\n\n"); buffer = entries.pop() ?? "";
      for (const entry of entries) for (const line of entry.split("\n")) if (line.startsWith("data:")) yield line.slice(5).trim();
    }
  }
}

function safeJson(value: string): unknown { try { return JSON.parse(value); } catch { return value; } }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
