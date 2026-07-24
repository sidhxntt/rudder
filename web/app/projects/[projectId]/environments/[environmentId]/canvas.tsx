"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeChange,
  type NodeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";

import { useDomains, useServices, useUpdateServicePosition } from "@/lib/queries";
import { serviceUrl } from "@/lib/status";
import type { Service } from "@/lib/types";

import { DetailPanel } from "./detail-panel";
import { composeManagedByServiceId, composeReleaseOwnerId } from "./compose-lifecycle";
import { ServiceNode, type ServiceNodeData } from "./service-node";
import { GitHubImportDialog } from "./github-import-dialog";

const nodeTypes: NodeTypes = { service: ServiceNode };

/** Node box is 14rem wide; these leave a lane between columns. */
const FALLBACK_COLUMN = 288;
const FALLBACK_ROW = 176;
const FALLBACK_PER_COLUMN = 3;

/**
 * Where to draw a service that has never been dragged.
 *
 * `canvas_x`/`canvas_y` default to 0 server-side, so a freshly created
 * environment hands back every service stacked on the same point and the canvas
 * looks like it has one node. A stored (0, 0) therefore means "unplaced" and
 * gets a deterministic grid slot instead. Nothing is written back for it — the
 * position is persisted the first time the operator drags, which is the only
 * moment they have expressed an opinion about layout (D6).
 */
function initialPosition(service: Service, index: number): { x: number; y: number } {
  if (service.canvas_x !== 0 || service.canvas_y !== 0) {
    return { x: service.canvas_x, y: service.canvas_y };
  }
  return {
    x: Math.floor(index / FALLBACK_PER_COLUMN) * FALLBACK_COLUMN,
    y: (index % FALLBACK_PER_COLUMN) * FALLBACK_ROW,
  };
}

/**
 * No edges. Service-to-service links would have to come from reference
 * Variables (`${{postgres.DATABASE_URL}}`), and the API never returns a
 * variable's value — so the relationship is not derivable client-side. Phase 1
 * step 10 asks for nodes, and nodes are what this draws.
 */
const NO_EDGES: Edge[] = [];

export function EnvironmentCanvas({ environmentId }: { environmentId: string }) {
  const services = useServices(environmentId);
  const domains = useDomains(environmentId);
  const updatePosition = useUpdateServicePosition(environmentId);

  const [nodes, setNodes] = useState<Node[]>([]);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);

  const serviceList = useMemo(() => services.data ?? [], [services.data]);
  const domainList = useMemo(() => domains.data ?? [], [domains.data]);
  const composeAppServiceId = useMemo(() => composeReleaseOwnerId(serviceList), [serviceList]);

  // Rebuild nodes when the service set changes. Positions already on screen are
  // kept: a drag in flight must not be yanked back by a poll. Layout is UI
  // metadata (D6) — the server is told about it, it is never told back.
  useEffect(() => {
    setNodes((current) => {
      const byId = new Map(current.map((node) => [node.id, node]));
      return serviceList.map((service, index) => {
        const existing = byId.get(service.id);
        const data: ServiceNodeData = {
          serviceId: service.id,
          name: service.name,
          kind: service.kind,
          role:
            typeof service.build_config.compose_role === "string"
              ? service.build_config.compose_role
              : undefined,
          url: serviceUrl(service, domainList),
          managedByServiceId: composeManagedByServiceId(service, composeAppServiceId),
        };
        return {
          id: service.id,
          type: "service",
          position: existing ? existing.position : initialPosition(service, index),
          selected: existing ? existing.selected : false,
          data,
        } satisfies Node;
      });
    });
  }, [serviceList, domainList]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
  }, []);

  /**
   * D6: this PATCH carries `canvas_x`/`canvas_y` and nothing else. It is a
   * layout write against a CRUD endpoint — no deploy, no reconciliation, no
   * container touched.
   */
  const onNodeDragStop = useCallback<OnNodeDrag>(
    (_event, node) => {
      updatePosition.mutate({
        serviceId: node.id,
        patch: { canvas_x: Math.round(node.position.x), canvas_y: Math.round(node.position.y) },
      });
    },
    [updatePosition],
  );

  const onNodeClick = useCallback((_event: MouseEvent, node: Node) => {
    setSelectedServiceId(node.id);
  }, []);

  const selectedService = serviceList.find((service) => service.id === selectedServiceId) ?? null;

  return (
    <div className="flex h-full min-h-0 w-full">
      <div className="relative min-w-0 flex-1">
        <div className="absolute left-5 top-5 z-10">
          <GitHubImportDialog />
        </div>
        <ReactFlow
          nodes={nodes}
          edges={NO_EDGES}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={onNodeClick}
          onPaneClick={() => setSelectedServiceId(null)}
          nodesConnectable={false}
          fitView
          fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
          minZoom={0.4}
          maxZoom={1.6}
          style={{ backgroundColor: "var(--rd-surface)" }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="var(--rd-hairline)"
          />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>

        {services.isSuccess && serviceList.length === 0 ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <p className="text-caption text-ink-faint">
              no services in this environment — create one with{" "}
              <span className="font-mono text-ink-mute">rudder service create</span>
            </p>
          </div>
        ) : null}

        {services.isError ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <p className="text-caption text-status-failed">could not load services</p>
          </div>
        ) : null}
      </div>

      {selectedService ? (
        <DetailPanel
          service={selectedService}
          url={serviceUrl(selectedService, domainList)}
          managedByServiceId={composeManagedByServiceId(selectedService, composeAppServiceId)}
          onClose={() => setSelectedServiceId(null)}
        />
      ) : null}
    </div>
  );
}
