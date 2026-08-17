"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

export function AdvisorNode(props: NodeProps) {
  const data = props.data as { name: string; kind: string; onAccept: () => void };
  return <div className="w-56 rounded-md border border-dashed border-accent/70 bg-accent/5 p-md shadow-elev-1">
    <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-accent/40" />
    <p className="font-mono text-micro uppercase tracking-wide text-accent">ghost proposal · {data.kind}</p>
    <p className="mt-xs text-caption font-medium text-ink">{data.name}</p>
    <p className="mt-xxs text-micro text-ink-mute">Not a service until accepted.</p>
    <button type="button" onClick={(event) => { event.stopPropagation(); data.onAccept(); }} className="nodrag mt-sm text-micro text-accent underline">Accept this item</button>
    <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-accent/40" />
  </div>;
}
