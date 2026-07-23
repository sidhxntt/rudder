"use client";

import { useEffect, useRef } from "react";

import { useBuildLog } from "@/lib/queries";
import type { Deployment } from "@/lib/types";

const TERMINAL: ReadonlySet<Deployment["status"]> = new Set<Deployment["status"]>([
  "live",
  "failed",
  "superseded",
]);

/**
 * BUILD logs. Not runtime logs — those are Phase 5 (D4) and no view for them
 * exists anywhere in this tree.
 */
export function BuildLogs({ deployment }: { deployment: Deployment | null }) {
  const complete = deployment ? TERMINAL.has(deployment.status) : true;
  const log = useBuildLog(deployment?.id, complete);
  const endRef = useRef<HTMLDivElement>(null);

  const lines = log.data?.lines ?? [];

  useEffect(() => {
    if (!complete) endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length, complete]);

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
        <span className="font-mono text-micro text-ink-mute">{deployment.commit_sha}</span>
        <span className="text-micro text-ink-faint">
          {complete ? "build complete" : "streaming…"}
        </span>
      </div>

      <div className="rd-scroll min-h-0 flex-1 overflow-auto bg-surface-inset px-lg py-md">
        {log.isPending ? (
          <p className="font-mono text-micro text-ink-faint">opening log…</p>
        ) : null}

        {lines.map((line, index) => (
          <p
            key={`${index}-${line}`}
            className="whitespace-pre-wrap break-all font-mono text-micro leading-relaxed text-ink-secondary"
          >
            {line}
          </p>
        ))}

        {!log.isPending && lines.length === 0 ? (
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
