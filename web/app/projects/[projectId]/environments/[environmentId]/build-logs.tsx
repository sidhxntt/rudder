"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, isNotFound, streamBuildLog } from "@/lib/api";
import type { Deployment } from "@/lib/types";

type Stream =
  | { phase: "idle" }
  | { phase: "waiting" }
  | { phase: "streaming" }
  | { phase: "ended"; outcome: string }
  | { phase: "missing" }
  | { phase: "error"; message: string };

const LOG_RETRY_MS = 1_000;
const MAX_LOG_RETRIES = 60;
const TERMINAL: ReadonlySet<Deployment["status"]> = new Set([
  "live",
  "failed",
  "superseded",
]);

/**
 * BUILD logs. Not runtime logs — those are Phase 5 (D4) and no view for them
 * exists anywhere in this tree.
 *
 * One SSE subscription per selected deployment, opened on mount and aborted on
 * unmount or when the selection changes. A just-queued deployment has no log
 * file until its worker starts, so a 404 retries briefly rather than becoming a
 * permanent "no log" result. The stream ends by itself on the terminal `event:
 * end` frame and the connection is dropped right there, so a finished build
 * leaves no socket open.
 *
 * Disconnecting is safe by construction: the control plane tails a log *file*,
 * the deploy worker writes it, and the two share nothing else. Closing this
 * panel mid-build cannot stop the build.
 */
export function BuildLogs({ deployment }: { deployment: Deployment | null }) {
  const [lines, setLines] = useState<string[]>([]);
  const [stream, setStream] = useState<Stream>({ phase: "idle" });
  const [logAttempt, setLogAttempt] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);
  const statusRef = useRef<Deployment["status"] | null>(null);

  const deploymentId = deployment?.id ?? null;
  statusRef.current = deployment?.status ?? null;

  useEffect(() => {
    setLines([]);
    setLogAttempt(0);

    if (!deploymentId) setStream({ phase: "idle" });
  }, [deploymentId]);

  useEffect(() => {
    if (!deploymentId) {
      return;
    }

    setStream({ phase: "streaming" });
    const controller = new AbortController();
    let retryTimer: number | undefined;

    void streamBuildLog(
      deploymentId,
      {
        onLines: (batch) => setLines((current) => [...current, ...batch]),
        onEnd: (outcome) => setStream({ phase: "ended", outcome }),
      },
      controller.signal,
    ).catch((cause: unknown) => {
      if (controller.signal.aborted) return; // unmount, not a failure
      if (isNotFound(cause)) {
        if (!TERMINAL.has(statusRef.current ?? "failed") && logAttempt < MAX_LOG_RETRIES) {
          setStream({ phase: "waiting" });
          retryTimer = window.setTimeout(() => setLogAttempt((attempt) => attempt + 1), LOG_RETRY_MS);
          return;
        }
        setStream({ phase: "missing" });
        return;
      }
      // During a control-plane restart a healthy deployment can briefly see a
      // 5xx (or a browser-level network error) before its log endpoint comes
      // back. Treat that exactly like a not-yet-created log while the release
      // is non-terminal. Otherwise the panel gets permanently stuck on
      // "stream failed" even though Docker and the control plane recover.
      if (isTransientLogError(cause) && !TERMINAL.has(statusRef.current ?? "failed")) {
        if (logAttempt < MAX_LOG_RETRIES) {
          setStream({ phase: "waiting" });
          retryTimer = window.setTimeout(() => setLogAttempt((attempt) => attempt + 1), LOG_RETRY_MS);
          return;
        }
      }
      setStream({
        phase: "error",
        message: cause instanceof Error ? cause.message : "the log stream failed",
      });
    });

    return () => {
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [deploymentId, logAttempt]);

  // Follow the tail only while output is still arriving.
  useEffect(() => {
    if (stream.phase === "streaming") endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length, stream.phase]);

  if (!deployment) {
    return (
      <p className="px-lg py-md text-micro text-ink-faint">
        no deployments yet — nothing has been built
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-hairline-faint px-lg py-sm">
        <span className="font-mono text-micro text-ink-mute">
          {deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : "no commit"}
        </span>
        <span className="text-micro text-ink-faint">{statusLine(stream)}</span>
      </div>

      <div className="rd-scroll min-h-0 flex-1 overflow-auto bg-surface-inset px-lg py-md">
        {stream.phase === "waiting" ? (
          <p className="font-mono text-micro text-ink-faint">waiting for the build to start…</p>
        ) : null}

        {stream.phase === "streaming" && lines.length === 0 ? (
          <p className="font-mono text-micro text-ink-faint">opening log…</p>
        ) : null}

        {stream.phase === "missing" ? (
          <p className="font-mono text-micro text-ink-faint">
            no build log — this deployment never reached the builder
          </p>
        ) : null}

        {stream.phase === "error" ? (
          <p className="font-mono text-micro text-status-failed">{stream.message}</p>
        ) : null}

        {lines.map((line, index) => (
          <p
            key={`${index}-${line}`}
            className="whitespace-pre-wrap break-all font-mono text-micro leading-relaxed text-ink-secondary"
          >
            {line}
          </p>
        ))}

        {stream.phase === "ended" && lines.length === 0 ? (
          <p className="font-mono text-micro text-ink-faint">no build output</p>
        ) : null}

        {deployment.error_message ? (
          <p className="pt-md font-mono text-micro text-status-failed">
            {deployment.error_message}
          </p>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  );
}

function isTransientLogError(cause: unknown): boolean {
  return (
    cause instanceof TypeError ||
    (cause instanceof ApiError && cause.status >= 500 && cause.status <= 599)
  );
}

function statusLine(stream: Stream): string {
  switch (stream.phase) {
    case "idle":
      return "";
    case "waiting":
      return "waiting for build…";
    case "streaming":
      return "streaming…";
    case "ended":
      return `build ${stream.outcome}`;
    case "missing":
      return "no log";
    case "error":
      return "stream failed";
  }
}
