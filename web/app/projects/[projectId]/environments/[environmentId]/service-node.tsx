"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { useDeployments, useInstances, useRenameService } from "@/lib/queries";
import { deriveServiceStatus, latestDeployment } from "@/lib/status";
import type { ServiceKind } from "@/lib/types";

import { StatusDot } from "./status-dot";

export type ServiceNodeData = {
  serviceId: string;
  name: string;
  kind: ServiceKind;
  role?: string;
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
  const params = useParams();
  const environmentId = typeof params?.environmentId === "string" ? params.environmentId : undefined;
  const lifecycleServiceId = data.managedByServiceId ?? data.serviceId;
  const deployments = useDeployments(lifecycleServiceId);
  const instances = useInstances(lifecycleServiceId);
  const rename = useRenameService(environmentId);
  const [editingName, setEditingName] = useState(false);
  const [name, setName] = useState(data.name);

  useEffect(() => {
    if (!editingName) setName(data.name);
  }, [data.name, editingName]);

  async function saveName() {
    if (!name.trim() || name.trim() === data.name) {
      setEditingName(false);
      return;
    }
    await rename.mutateAsync({ serviceId: data.serviceId, name: name.trim() });
    setEditingName(false);
  }

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
      <Handle
        type="target"
        position={Position.Left}
        aria-label={`Connection into ${data.name}`}
        className="!h-2 !w-2 !border-0 !bg-transparent"
      />
      <div className="flex items-center justify-between gap-sm border-b border-hairline-faint px-md py-sm">
        {editingName ? (
          <Input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => void saveName()}
            onClick={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter") void saveName();
              if (event.key === "Escape") setEditingName(false);
            }}
            aria-label={`Rename ${data.name}`}
            className="nodrag h-7 min-w-0 font-sans"
          />
        ) : (
          <button
            type="button"
            onDoubleClick={(event) => {
              event.stopPropagation();
              setEditingName(true);
            }}
            title="Double-click to rename service"
            className="nodrag min-w-0 truncate text-left text-caption font-medium text-ink outline-none hover:text-accent focus-visible:text-accent"
          >
            {data.name}
          </button>
        )}
        <span className="shrink-0 rounded-xs border border-hairline px-xs py-xxs text-micro text-ink-mute">
          {data.role ?? KIND_LABEL[data.kind]}
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
      <Handle
        type="source"
        position={Position.Right}
        aria-label={`Connection out of ${data.name}`}
        className="!h-2 !w-2 !border-0 !bg-transparent"
      />
    </div>
  );
}
