"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeChange,
  type NodeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";

import {
  useDomains,
  useEnvironments,
  useServices,
  useUpdateServicePosition,
} from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { serviceUrl } from "@/lib/status";
import type { Service } from "@/lib/types";
import type { AdvisorProposal } from "@/lib/types";
import { acceptAdvisorItem, scanAdvisor } from "@/lib/api";

import { DetailPanel } from "./detail-panel";
import { composeManagedByServiceId, composeReleaseOwnerId } from "./compose-lifecycle";
import { ServiceNode, type ServiceNodeData } from "./service-node";
import { AdvisorNode } from "./advisor-node";
import { ProjectSettings } from "./project-settings";

const nodeTypes: NodeTypes = { service: ServiceNode, advisor: AdvisorNode };

/** Node box is 14rem wide; these leave a lane between columns. */
const FALLBACK_COLUMN = 288;
const FALLBACK_ROW = 176;
const FALLBACK_PER_COLUMN = 3;

/** All protected return controls lead to the signed-in workspace, never the public site. */
export function workspaceDashboardHref(): "/dashboard" {
  return "/dashboard";
}

export type CanvasOperatorContext = {
  eyebrow: "Deployment topology";
  title: string;
  description: string;
  command: string | null;
};

/**
 * The canvas should orient an operator before it asks them to interpret a
 * topology. This remains intentionally factual: it describes only the
 * service map and the panel already available in this route.
 */
export function canvasOperatorContext({
  serviceCount,
  selectedServiceName,
}: {
  serviceCount: number;
  selectedServiceName: string | null;
}): CanvasOperatorContext {
  if (serviceCount === 0) {
    return {
      eyebrow: "Deployment topology",
      title: "No service topology yet",
      description: "Create a service to map its release and private dependencies here.",
      command: "rudder service create",
    };
  }

  if (selectedServiceName) {
    return {
      eyebrow: "Deployment topology",
      title: `${selectedServiceName} selected`,
      description: "Inspect its release, runtime, and private connections in the panel.",
      command: null,
    };
  }

  return {
    eyebrow: "Deployment topology",
    title: `${serviceCount} ${serviceCount === 1 ? "service" : "services"} mapped`,
    description: "Select a service to inspect it, or drag it to arrange the release path.",
    command: null,
  };
}

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
 * Imported Compose releases have one route-owning application and a set of
 * services that share its lifecycle. That persisted ownership is enough to
 * render a truthful topology without exposing variable values or guessing at
 * application-level connections.
 */
export function composeEdges(services: Service[], releaseOwnerId: string | undefined): Edge[] {
  if (!releaseOwnerId) return [];

  const serviceById = new Map(services.map((service) => [service.id, service]));
  const owner = serviceById.get(releaseOwnerId);
  if (!owner) return [];

  return services.flatMap((service) => {
    const ownerId = composeManagedByServiceId(service, releaseOwnerId);
    if (ownerId !== releaseOwnerId || service.id === releaseOwnerId) return [];

    // Lifecycle ownership shows that the services were released together. It
    // does not prove an application-level dependency, so the edge deliberately
    // names only that recorded release relationship.
    const relationship = "included in release";

    return [{
      id: `compose-${releaseOwnerId}-${service.id}`,
      source: releaseOwnerId,
      target: service.id,
      type: "smoothstep",
      label: relationship,
      ariaLabel: `${owner.name} includes ${service.name} in its release`,
      focusable: true,
      interactionWidth: 18,
      markerEnd: { type: MarkerType.ArrowClosed, color: "var(--rd-hairline-strong)" },
      style: { stroke: "var(--rd-hairline-strong)", strokeWidth: 1.25 },
      labelStyle: { fill: "var(--rd-text-mute)", fontSize: 11, fontWeight: 500 },
      labelBgStyle: { fill: "var(--rd-surface)", fillOpacity: 0.92 },
      labelBgPadding: [4, 3] as [number, number],
      labelBgBorderRadius: 4,
    } satisfies Edge];
  });
}

export function composeAdvisorGraph(items: AdvisorProposal["items"]): { nodes: Node[]; edges: Edge[] } {
  const nodes = items.filter((item) => item.kind !== "variable").map((item, index) => ({
    id: `advisor:${item.id}`, type: "advisor", position: { x: 600, y: index * 176 },
    data: { name: String(item.payload.name ?? item.payload.template ?? item.id), kind: item.kind },
  } satisfies Node));
  const edges = items.filter((item) => item.kind === "variable").flatMap((item) => {
    const service = String(item.payload.service ?? "app");
    const addon = String(item.payload.key ?? "").startsWith("DATABASE") ? "postgres" : "redis";
    return [{ id: `advisor:${item.id}`, source: `advisor:service:${service}`, target: `advisor:addon:${addon}`, type: "smoothstep", animated: true, style: { stroke: "var(--rd-accent)", strokeDasharray: "5 4" } } satisfies Edge];
  });
  return { nodes, edges };
}

export function resolveAdvisorVariableTarget(
  selectedId: string, proposedName: unknown, services: Pick<Service, "id" | "name">[],
): string | undefined {
  return selectedId || services.find((service) => service.name === proposedName)?.id;
}

export function EnvironmentCanvas({ environmentId }: { environmentId: string }) {
  const params = useParams();
  const router = useRouter();
  const projectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const environments = useEnvironments(projectId);
  const services = useServices(environmentId);
  const domains = useDomains(environmentId);
  const updatePosition = useUpdateServicePosition(environmentId);

  const [nodes, setNodes] = useState<Node[]>([]);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);
  const [projectSettingsOpen, setProjectSettingsOpen] = useState(false);
  const [advisorPath, setAdvisorPath] = useState("");
  const [advisorProposal, setAdvisorProposal] = useState<AdvisorProposal | null>(null);
  const [advisorMessage, setAdvisorMessage] = useState("");
  const [advisorVariableTarget, setAdvisorVariableTarget] = useState("");

  const serviceList = useMemo(() => services.data ?? [], [services.data]);
  const domainList = useMemo(() => domains.data ?? [], [domains.data]);
  const composeAppServiceId = useMemo(() => composeReleaseOwnerId(serviceList), [serviceList]);
  const edges = useMemo(() => composeEdges(serviceList, composeAppServiceId), [composeAppServiceId, serviceList]);
  const advisorGraph = useMemo(() => composeAdvisorGraph(advisorProposal?.items ?? []), [advisorProposal]);
  const canvasNodes = useMemo(() => [...nodes, ...advisorGraph.nodes.map((node) => ({ ...node, data: { ...node.data, onAccept: () => void acceptProposal(node.id.replace("advisor:", "")) } }))], [nodes, advisorGraph.nodes]);
  const canvasEdges = useMemo(() => [...edges, ...advisorGraph.edges], [edges, advisorGraph.edges]);

  async function acceptProposal(id: string) {
    const item = advisorProposal?.items.find((candidate) => candidate.id === id);
    if (!item) return;
    const target = item.kind === "variable"
      ? resolveAdvisorVariableTarget(advisorVariableTarget, item.payload.service, serviceList)
      : undefined;
    if (item.kind === "variable" && !target) { setAdvisorMessage("Accept the proposed target service before its variable."); return; }
    try { await acceptAdvisorItem(environmentId, item, target); setAdvisorProposal((current) => current && { ...current, items: current.items.filter((candidate) => candidate.id !== id) }); }
    catch (error) { setAdvisorMessage(error instanceof Error ? error.message : "Could not accept proposal"); }
  }

  async function scanAdvisorProposal() {
    try { setAdvisorMessage(""); setAdvisorProposal(await scanAdvisor(environmentId, advisorPath)); }
    catch (error) { setAdvisorMessage(error instanceof Error ? error.message : "Advisor scan failed"); }
  }

  // A local bootstrap can replace an environment while a browser still has its
  // old URL open. Resolve the project again instead of leaving the canvas on a
  // permanent 404; the project route selects its production environment.
  useEffect(() => {
    if (
      projectId &&
      environments.isSuccess &&
      !environments.data?.some((environment) => environment.id === environmentId)
    ) {
      router.replace(`/projects/${projectId}`);
    }
  }, [environmentId, environments.data, environments.isSuccess, projectId, router]);

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
    setProjectSettingsOpen(false);
  }, []);

  const selectedService = serviceList.find((service) => service.id === selectedServiceId) ?? null;
  const operatorContext = canvasOperatorContext({
    serviceCount: serviceList.length,
    selectedServiceName: selectedService?.name ?? null,
  });

  return (
    <div className="flex h-full min-h-0 w-full">
      <div className="relative min-w-0 flex-1">
        <section
          aria-label="Deployment canvas context"
          aria-live="polite"
          className="absolute left-5 top-5 z-10 w-[20rem] overflow-hidden rounded-md border border-hairline-strong bg-surface-soft/95 shadow-elev-2 backdrop-blur-sm"
        >
          <div className="flex items-center justify-between gap-md border-b border-hairline px-md py-sm">
            <span className="font-mono text-micro font-medium uppercase tracking-[0.12em] text-ink-mute">
              {operatorContext.eyebrow}
            </span>
            <div className="flex items-center gap-xs" aria-label="Canvas actions">
              <Button
                variant="outline"
                size="icon"
                onClick={() => router.push(workspaceDashboardHref())}
                aria-label="Back to workspace dashboard"
                title="Back to workspace dashboard"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 fill-none stroke-current stroke-[1.8]">
                  <path d="M19 12H5M11 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Button>
              <Button
                variant="outline"
                size="icon"
                aria-label="Open project settings"
                title="Project settings"
                onClick={() => {
                  setSelectedServiceId(null);
                  setProjectSettingsOpen(true);
                }}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 fill-none stroke-current stroke-[1.7]">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.08 2.08-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.04 1.56V20.3h-2.96v-.12A1.7 1.7 0 0 0 10.74 18.6a1.7 1.7 0 0 0-1.88.34l-.06.06-2.08-2.08.06-.06A1.7 1.7 0 0 0 7.12 15a1.7 1.7 0 0 0-1.56-1.04H5.44v-2.96h.12A1.7 1.7 0 0 0 7.12 9.96a1.7 1.7 0 0 0-.34-1.88l-.06-.06L8.8 5.94l.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.04-1.56v-.12h2.96v.12a1.7 1.7 0 0 0 1.04 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.08 2.08-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.04h.12v2.96h-.12A1.7 1.7 0 0 0 19.4 15Z" />
                </svg>
              </Button>
            </div>
          </div>
          <div className="px-md py-md">
            <p className="text-heading-md text-ink">{operatorContext.title}</p>
            <p className="mt-xxs max-w-[31ch] text-caption leading-relaxed text-ink-mute">
              {operatorContext.description}
            </p>
          </div>
          <div className="border-t border-hairline px-md py-sm">
            <p className="font-mono text-micro uppercase tracking-wide text-accent">Advisor · ghost proposals</p>
            <div className="mt-xs flex gap-xs"><input value={advisorPath} onChange={(event) => setAdvisorPath(event.target.value)} placeholder="checkout path" aria-label="Advisor checkout path" className="min-w-0 flex-1 rounded-sm border border-hairline bg-surface px-xs py-xxs text-micro" /><button type="button" onClick={() => void scanAdvisorProposal()} disabled={!advisorPath} className="text-micro text-accent disabled:opacity-50">Scan</button></div>
            {advisorProposal?.items.some((item) => item.kind === "variable") ? <select value={advisorVariableTarget} onChange={(event) => setAdvisorVariableTarget(event.target.value)} aria-label="Variable target service" className="mt-xs w-full rounded-sm border border-hairline bg-surface px-xs py-xxs text-micro"><option value="">Select target service for variables</option>{serviceList.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select> : null}
            {advisorProposal?.items.filter((item) => item.kind === "variable").map((item) => <div key={item.id} className="mt-xs flex items-center justify-between text-micro text-ink-mute"><span>ghost · {String(item.payload.key)}</span><button type="button" onClick={() => void acceptProposal(item.id)} className="text-accent underline">Accept</button></div>)}
            {advisorMessage ? <p className="mt-xxs text-micro text-status-failed">{advisorMessage}</p> : null}
          </div>
        </section>
        <ReactFlow
          nodes={canvasNodes}
          edges={canvasEdges}
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
          proOptions={{ hideAttribution: true }}
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
            <section aria-labelledby="empty-topology-title" className="w-full max-w-sm px-lg text-center">
              <svg viewBox="0 0 168 72" aria-hidden="true" className="mx-auto h-[4.5rem] w-[10.5rem] fill-none">
                <path d="M53 36h62M53 36l18-18M53 36l18 18" stroke="var(--rd-hairline-strong)" strokeWidth="1.5" strokeLinecap="round" />
                <circle cx="42" cy="36" r="10" stroke="var(--rd-accent)" strokeWidth="1.5" />
                <circle cx="126" cy="18" r="10" stroke="var(--rd-hairline-strong)" strokeWidth="1.5" />
                <circle cx="126" cy="54" r="10" stroke="var(--rd-hairline-strong)" strokeWidth="1.5" />
                <circle cx="42" cy="36" r="3" fill="var(--rd-accent)" />
              </svg>
              <h2 id="empty-topology-title" className="mt-lg text-heading-lg text-ink">Start with a service</h2>
              <p className="mx-auto mt-xs max-w-[34ch] text-caption leading-relaxed text-ink-mute">
                Your release path and private dependencies will appear here as services are added.
              </p>
              <p className="mt-md font-mono text-micro text-accent">{operatorContext.command}</p>
            </section>
          </div>
        ) : null}

        {services.isError ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <p className="text-caption text-status-failed">could not load services</p>
          </div>
        ) : null}
      </div>

      {projectSettingsOpen ? (
        <aside className="flex w-[30rem] shrink-0 flex-col border-l border-hairline bg-surface-soft">
          <div className="flex items-center justify-between gap-md border-b border-hairline px-lg py-md">
            <h2 className="text-heading-md text-ink">Project settings</h2>
            <button
              type="button"
              onClick={() => setProjectSettingsOpen(false)}
              aria-label="Close project settings"
              className="rounded-xs px-xs py-xxs text-micro text-ink-faint hover:text-ink"
            >
              ✕
            </button>
          </div>
          <ProjectSettings />
        </aside>
      ) : selectedService ? (
        <DetailPanel
          service={selectedService}
          url={serviceUrl(selectedService, domainList)}
          domains={domainList}
          managedByServiceId={composeManagedByServiceId(selectedService, composeAppServiceId)}
          onClose={() => setSelectedServiceId(null)}
        />
      ) : null}
    </div>
  );
}
