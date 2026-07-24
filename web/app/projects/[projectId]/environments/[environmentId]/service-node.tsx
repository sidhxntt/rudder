"use client";

import type { NodeProps } from "@xyflow/react";

import { useDeployments, useInstances } from "@/lib/queries";
import { deriveServiceStatus, latestDeployment } from "@/lib/status";
import type { ServiceKind } from "@/lib/types";

import { StatusDot } from "./status-dot";

export type ServiceNodeData = {
  serviceId: string;
  name: string;
  kind: ServiceKind;
  url: string | null;
  /** Compose dependencies share the application release and its lifecycle. */
  managedByServiceId?: string;
};

const KIND_LABEL: Record<ServiceKind, string> = {
  app: "app",
  database: "database",
  static: "static",
};

/**
 * One node per Service. Name, status, URL — nothing else. Status is derived
 * here from the service's own Deployment and Instance records, which is why the
 * node owns its queries rather than being handed a precomputed blob.
 */
export function ServiceNode(props: NodeProps) {
  const data = props.data as ServiceNodeData;
  const lifecycleServiceId = data.managedByServiceId ?? data.serviceId;
  const deployments = useDeployments(lifecycleServiceId);
  const instances = useInstances(lifecycleServiceId);

  const status = deriveServiceStatus(deployments.data ?? [], instances.data ?? []);
  const latest = latestDeployment(deployments.data ?? []);
  const failedWhileServing = status === "live" && latest?.status === "failed";

  return (
    <div
      className={[
        "w-56 rounded-md border bg-surface-raised shadow-elev-1 transition-colors",
        props.selected ? "border-accent" : "border-hairline hover:border-hairline-strong",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-sm border-b border-hairline-faint px-md py-sm">
        <span className="truncate text-caption font-medium text-ink">{data.name}</span>
        <span className="shrink-0 rounded-xs border border-hairline px-xs py-xxs text-micro text-ink-mute">
          {KIND_LABEL[data.kind]}
        </span>
      </div>

      <div className="flex items-start justify-between gap-sm px-md py-sm">
        <div className="min-w-0">
          <StatusDot status={status} />
          {data.managedByServiceId ? (
            <p className="pt-xxs text-micro text-ink-mute">managed by Compose</p>
          ) : null}
          {failedWhileServing ? (
            <p className="pt-xxs text-micro text-status-failed">latest deploy failed</p>
          ) : null}
        </div>
        {deployments.isPending ? <span className="text-micro text-ink-faint">…</span> : null}
      </div>

      <div className="border-t border-hairline-faint px-md py-sm">
        {data.url ? (
          <span className="block truncate font-mono text-micro text-ink-mute">
            {data.url.replace(/^https?:\/\//, "")}
          </span>
        ) : (
          <span className="block truncate text-micro text-ink-faint">no public domain</span>
        )}
      </div>
    </div>
  );
}
