"use client";

import type { NodeProps } from "@xyflow/react";

import { useDeployments, useInstances } from "@/lib/queries";
import { deriveServiceStatus } from "@/lib/status";
import type { ServiceKind } from "@/lib/types";

import { StatusDot } from "./status-dot";

export type ServiceNodeData = {
  serviceId: string;
  name: string;
  kind: ServiceKind;
  url: string | null;
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
  const deployments = useDeployments(data.serviceId);
  const instances = useInstances(data.serviceId);

  const status = deriveServiceStatus(deployments.data ?? [], instances.data ?? []);

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

      <div className="flex items-center justify-between gap-sm px-md py-sm">
        <StatusDot status={status} />
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
