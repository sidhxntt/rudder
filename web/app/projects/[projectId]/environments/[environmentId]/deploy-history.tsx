"use client";

import { shortAgo } from "@/lib/status";
import type { Deployment, DeploymentStatus } from "@/lib/types";

const STATUS_COLOR: Record<DeploymentStatus, string> = {
  queued: "text-status-building",
  building: "text-status-building",
  deploying: "text-status-building",
  live: "text-status-live",
  failed: "text-status-failed",
  superseded: "text-status-draining",
};

export function DeployHistory({
  deployments,
  selectedId,
  onSelect,
  onRollback,
  rollbackPending = false,
}: {
  deployments: readonly Deployment[];
  selectedId: string | null;
  onSelect: (deploymentId: string) => void;
  onRollback?: (deploymentId: string) => void;
  rollbackPending?: boolean;
}) {
  if (deployments.length === 0) {
    return <p className="px-lg py-md text-micro text-ink-faint">no deployments yet</p>;
  }

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse">
        <tbody>
          {deployments.map((deployment) => {
            const canRollback =
              Boolean(deployment.image_tag) &&
              deployment.status === "superseded";
            return (
            <tr
              key={deployment.id}
              onClick={() => onSelect(deployment.id)}
              className={[
                "cursor-pointer border-b border-hairline-faint",
                deployment.id === selectedId ? "bg-surface-raised" : "hover:bg-surface-raised",
              ].join(" ")}
            >
              <td className="px-lg py-sm">
                {/* Nullable: a deploy that dies before the clone resolves
                    never gets a SHA. That is exactly the row worth reading. */}
                <span className="font-mono text-micro text-ink">
                  {deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : "—"}
                </span>
              </td>
              <td className="py-sm">
                <span className={`text-micro ${STATUS_COLOR[deployment.status]}`}>
                  {deployment.status}
                </span>
              </td>
              <td className="py-sm">
                <span className="text-micro text-ink-mute">{shortAgo(deployment.created_at)}</span>
              </td>
              <td className="px-lg py-sm text-right">
                <div className="flex items-center justify-end gap-sm">
                  <span className="text-micro text-ink-faint">
                    {deployment.became_live_at ? `live ${shortAgo(deployment.became_live_at)}` : "—"}
                  </span>
                  {canRollback && onRollback ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onRollback(deployment.id);
                      }}
                      disabled={rollbackPending}
                      className="rounded-xs border border-hairline-strong px-sm py-xxs text-micro text-ink-secondary hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Restore
                    </button>
                  ) : null}
                </div>
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-lg py-md text-micro text-ink-faint">
        Every deployment is an immutable artifact — image tags are never reused.
      </p>
    </div>
  );
}
