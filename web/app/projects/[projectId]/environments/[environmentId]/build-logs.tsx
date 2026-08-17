"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, diagnoseBuildFailure, isNotFound, streamBuildLog } from "@/lib/api";
import type { AdvisorDiagnosis } from "@/lib/types";
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
  const [followOutput, setFollowOutput] = useState(true);
  const [copied, setCopied] = useState(false);
  const [diagnosis, setDiagnosis] = useState<AdvisorDiagnosis | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const statusRef = useRef<Deployment["status"] | null>(null);

  const deploymentId = deployment?.id ?? null;
  statusRef.current = deployment?.status ?? null;

  useEffect(() => {
    setLines([]);
    setDiagnosis(null);
    setLogAttempt(0);

    if (!deploymentId) setStream({ phase: "idle" });
  }, [deploymentId]);

  useEffect(() => {
    if (deployment?.status !== "failed" || lines.length === 0) return;
    void diagnoseBuildFailure(lines).then(setDiagnosis).catch(() => setDiagnosis(null));
  }, [deployment?.status, lines]);

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

  // Follow the tail only while output is still arriving and the operator has
  // not paused it to inspect an earlier step.
  useEffect(() => {
    if (stream.phase === "streaming" && followOutput) endRef.current?.scrollIntoView({ block: "end" });
  }, [followOutput, lines.length, stream.phase]);

  async function copyOutput() {
    if (!lines.length || !navigator.clipboard) return;
    await navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }

  if (!deployment) {
    return (
      <p className="px-lg py-md text-micro text-ink-faint">
        no deployments yet — nothing has been built
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-hairline bg-surface-soft px-lg py-md">
        <div className="flex items-start justify-between gap-md">
          <div className="min-w-0">
            <p className="text-caption font-medium text-ink">Build logs</p>
            <div className="mt-xxs flex min-w-0 items-center gap-sm text-micro text-ink-mute">
              <span className="truncate font-mono">{deployment.image_tag ?? "source build"}</span>
              <span className="text-ink-faint" aria-hidden>·</span>
              <span className="shrink-0 font-mono text-ink-secondary">
                {deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : "no commit"}
              </span>
            </div>
          </div>
          <span className={statusClass(stream)}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
            {statusLine(stream)}
          </span>
        </div>
        <div className="mt-md flex items-center justify-between border-t border-hairline-faint pt-sm">
          <span className="font-mono text-micro text-ink-faint">
            $ rudder build {deployment.commit_sha?.slice(0, 7) ?? "source"}
          </span>
          <div className="flex items-center gap-xs">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setFollowOutput((following) => !following)}
              disabled={stream.phase !== "streaming"}
            >
              {followOutput ? "Following" : "Follow output"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void copyOutput()} disabled={!lines.length}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      </div>

      <div className="rd-scroll min-h-0 flex-1 overflow-auto bg-surface-inset py-md">
        {stream.phase === "waiting" ? (
          <LogNotice title="Waiting for builder" detail="The release is queued. Output will appear here as soon as the builder starts." />
        ) : null}

        {stream.phase === "streaming" && lines.length === 0 ? (
          <LogNotice title="Opening stream" detail="Connecting to the builder output…" live />
        ) : null}

        {stream.phase === "missing" ? (
          <LogNotice title="No build output" detail="This deployment never reached the builder." />
        ) : null}

        {stream.phase === "error" ? (
          <LogNotice title="Stream disconnected" detail={stream.message} tone="failed" />
        ) : null}

        <ol className="font-mono text-micro leading-5 text-ink-secondary">
          {lines.map((line, index) => {
            const level = logLevel(line);
            return (
              <li
                key={`${index}-${line}`}
                className="group grid grid-cols-[3.25rem_4.7rem_minmax(0,1fr)] gap-md px-lg py-px hover:bg-surface-soft/70"
              >
                <span className="select-none text-right text-ink-faint transition-colors group-hover:text-ink-mute">
                  {String(index + 1).padStart(3, "0")}
                </span>
                <span className={`select-none font-medium ${level.className}`}>[{level.label}]</span>
                <span className={`whitespace-pre-wrap break-words ${level.className}`}>{cleanLogMessage(line)}</span>
              </li>
            );
          })}
        </ol>

        {stream.phase === "ended" && lines.length === 0 ? (
          <LogNotice title="Build finished" detail="The builder completed without emitting output." />
        ) : null}

        {deployment.error_message ? (
          <div className="mx-lg mt-md border border-status-failed/30 bg-status-failed/5 px-md py-sm">
            <p className="text-micro font-medium text-status-failed">Build failed</p>
            <p className="pt-xxs font-mono text-micro leading-5 text-status-failed">{deployment.error_message}</p>
          </div>
        ) : null}

        {diagnosis?.enabled && diagnosis.diagnosis ? (
          <section className="mx-lg mt-md border border-accent/30 bg-accent/5 px-md py-sm" aria-label="Model-generated failure diagnosis">
            <p className="font-mono text-micro uppercase tracking-wide text-accent">Model-generated diagnosis</p>
            <p className="pt-xxs text-micro text-ink-secondary">{diagnosis.diagnosis}</p>
            <p className="pt-xs text-micro text-ink-faint">This is a suggestion. The raw build log above is the source of truth.</p>
          </section>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  );
}

function LogNotice({
  title,
  detail,
  tone = "quiet",
  live = false,
}: {
  title: string;
  detail: string;
  tone?: "quiet" | "failed";
  live?: boolean;
}) {
  return (
    <div className="px-lg py-lg">
      <div className="flex items-center gap-sm">
        {live ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden /> : null}
        <p className={`text-caption font-medium ${tone === "failed" ? "text-status-failed" : "text-ink-secondary"}`}>
          {title}
        </p>
      </div>
      <p className={`pt-xxs text-micro ${tone === "failed" ? "text-status-failed" : "text-ink-faint"}`}>{detail}</p>
    </div>
  );
}

type LogLevel = {
  label: "INFO" | "WARN" | "ERROR" | "SUCCESS";
  className: string;
};

function logLevel(line: string): LogLevel {
  if (/\[(?:error|fatal)\]|\b(error|failed|fatal|cannot|could not)\b/i.test(line)) {
    return { label: "ERROR", className: "text-status-failed" };
  }
  if (/\[(?:warn|warning)\]|\b(warn|warning|deprecated)\b/i.test(line)) {
    return { label: "WARN", className: "text-status-building" };
  }
  if (/\[(?:success|done)\]|\b(done|success|completed|built|ready)\b/i.test(line)) {
    return { label: "SUCCESS", className: "text-status-live" };
  }
  return { label: "INFO", className: "text-blue-400" };
}

function cleanLogMessage(line: string): string {
  return line.replace(/^\s*\[(?:info|warn(?:ing)?|error|fatal|success|done)\]\s*/i, "") || " ";
}

function statusClass(stream: Stream): string {
  const tone = stream.phase === "error" ? "text-status-failed" : stream.phase === "ended" ? "text-status-live" : "text-ink-mute";
  return `inline-flex shrink-0 items-center gap-xxs rounded-xs border border-hairline bg-surface-inset px-xs py-xxs text-micro ${tone}`;
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
