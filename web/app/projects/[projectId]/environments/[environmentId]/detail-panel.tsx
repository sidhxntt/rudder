"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDeploy, useDeployments, useInstances, useRenameService, useRollbackDeployment } from "@/lib/queries";
import { deriveServiceStatus, latestDeployment } from "@/lib/status";
import type { Domain, Service } from "@/lib/types";

import { BuildLogs } from "./build-logs";
import { DeployHistory } from "./deploy-history";
import { StatusDot } from "./status-dot";
import { Variables } from "./variables";
import { Operations } from "./operations";
import { Analytics } from "./analytics";
import { ServiceSettings } from "./service-settings";
import { AdvisorSurface } from "./advisor-surface";

export type ServiceTab = "logs" | "variables" | "deploys" | "operations" | "analytics" | "service-settings" | "advisor";

const TABS: readonly { id: ServiceTab; label: string }[] = [
  { id: "logs", label: "Build logs" },
  { id: "variables", label: "Variables" },
  { id: "deploys", label: "Deploys" },
  { id: "operations", label: "Operations" },
  { id: "analytics", label: "Analytics" },
  { id: "service-settings", label: "Service settings" },
  { id: "advisor", label: "Advisor" },
];

/** Navigation stays separate from the selected panel so every service view
 * presents the same compact, keyboard-reachable control surface. */
export function ServiceTabs({
  tab,
  onTabChange,
}: {
  tab: ServiceTab;
  onTabChange: (tab: ServiceTab) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Service views"
      className="rd-scroll flex shrink-0 items-center gap-lg overflow-x-auto border-b border-hairline px-lg"
    >
      {TABS.map((entry) => (
        <button
          key={entry.id}
          id={`${entry.id}-tab`}
          type="button"
          role="tab"
          aria-selected={tab === entry.id}
          aria-controls={`${entry.id}-panel`}
          onClick={() => onTabChange(entry.id)}
          className={[
            "-mb-px shrink-0 border-b py-sm text-micro transition-colors outline-none focus-visible:border-accent focus-visible:text-ink",
            tab === entry.id
              ? "border-ink text-ink"
              : "border-transparent text-ink-mute hover:text-ink-secondary",
          ].join(" ")}
        >
          {entry.label}
        </button>
      ))}
    </div>
  );
}

export function DetailPanel({
  service,
  url,
  domains,
  managedByServiceId,
  onClose,
}: {
  service: Service;
  url: string | null;
  domains: readonly Domain[];
  managedByServiceId?: string;
  onClose: () => void;
}) {
  const lifecycleServiceId = managedByServiceId ?? service.id;
  const isComposeManaged = managedByServiceId !== undefined;
  const deployments = useDeployments(lifecycleServiceId);
  const instances = useInstances(lifecycleServiceId);
  const deploy = useDeploy(service.id);
  const rollback = useRollbackDeployment(lifecycleServiceId);
  const rename = useRenameService(service.environment_id);

  const [tab, setTab] = useState<ServiceTab>("logs");
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [name, setName] = useState(service.name);

  // A different service means a different deploy history.
  useEffect(() => {
    setSelectedDeploymentId(null);
    setTab("logs");
    setEditingName(false);
    setName(service.name);
  }, [service.id]);

  useEffect(() => {
    if (!editingName) setName(service.name);
  }, [editingName, service.name]);

  async function saveServiceName() {
    if (!name.trim() || name.trim() === service.name) {
      setEditingName(false);
      return;
    }
    await rename.mutateAsync({ serviceId: service.id, name: name.trim() });
    setEditingName(false);
  }

  const list = deployments.data ?? [];
  const selectedDeployment =
    list.find((deployment) => deployment.id === selectedDeploymentId) ?? list[0] ?? null;

  const status = deriveServiceStatus(list, instances.data ?? []);
  const latest = latestDeployment(list);
  // A failed release must not obscure the healthy process that is still
  // serving traffic. Show both facts instead of reducing them to one status.
  const failedWhileServing =
    status === "live" && latest?.status === "failed" ? latest : null;

  return (
    <aside className="flex w-[30rem] shrink-0 flex-col border-l border-hairline bg-surface-soft">
      <div className="flex items-start justify-between gap-md border-b border-hairline px-lg py-md">
        <div className="min-w-0">
          <div className="flex items-center gap-sm">
            {editingName ? (
              <Input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                onBlur={() => void saveServiceName()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveServiceName();
                  if (event.key === "Escape") setEditingName(false);
                }}
                aria-label={`Rename ${service.name}`}
                className="h-8 min-w-0 font-sans text-heading-md"
              />
            ) : (
              <h2 className="min-w-0 truncate text-heading-md text-ink">
                <button
                  type="button"
                  onDoubleClick={() => setEditingName(true)}
                  title="Double-click to rename service"
                  className="truncate text-left outline-none hover:text-accent focus-visible:text-accent"
                >
                  {service.name}
                </button>
              </h2>
            )}
            <StatusDot status={status} />
          </div>
          <p className="truncate pt-xxs text-micro text-ink-mute">
            {service.source_repo ? (
              <span className="font-mono">
                {service.source_repo}
                {service.source_branch ? `@${service.source_branch}` : ""}
              </span>
            ) : (
              <span>
                {typeof service.build_config.compose_role === "string"
                  ? service.build_config.compose_role
                  : service.kind}
              </span>
            )}
          </p>
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="block truncate pt-xxs font-mono text-micro text-ink-secondary underline decoration-hairline-strong underline-offset-2 hover:text-ink"
            >
              {url.replace(/^https?:\/\//, "")}
            </a>
          ) : (
            <p className="pt-xxs text-micro text-ink-faint">no public domain</p>
          )}
          {isComposeManaged ? (
            <p className="pt-xs text-micro text-ink-mute">
              Managed by the application&apos;s Compose release.
            </p>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="shrink-0 rounded-xs px-xs py-xxs text-micro text-ink-faint hover:text-ink"
        >
          ✕
        </button>
      </div>

      <div className="flex items-center justify-between gap-md border-b border-hairline px-lg py-sm">
        <dl className="flex items-center gap-lg text-micro text-ink-mute">
          <div className="flex items-center gap-xs">
            <dt className="text-ink-faint">port</dt>
            <dd className="font-mono">{service.container_port}</dd>
          </div>
          <div className="flex items-center gap-xs">
            <dt className="text-ink-faint">cpu</dt>
            <dd className="font-mono">{service.cpu_limit}</dd>
          </div>
          <div className="flex items-center gap-xs">
            <dt className="text-ink-faint">mem</dt>
            <dd className="font-mono">{service.memory_limit_mb}m</dd>
          </div>
        </dl>

        {isComposeManaged ? (
          <span className="text-micro text-ink-mute">Managed by Compose</span>
        ) : (
          <Button
            onClick={() => deploy.mutate()}
            disabled={deploy.isPending || status === "building"}
            variant="default"
          >
            {status === "building" || deploy.isPending ? "Deploying…" : "Deploy"}
          </Button>
        )}
      </div>

      {failedWhileServing ? (
        <section
          aria-live="polite"
          className="border-b border-hairline bg-surface-inset px-lg py-sm"
        >
          <div className="flex flex-wrap items-baseline gap-x-sm gap-y-xxs">
            <p className="text-micro font-medium text-status-failed">latest deploy failed</p>
            <p className="text-micro text-ink-secondary">
              previous live deployment is still serving
            </p>
          </div>
          {failedWhileServing.error_message ? (
            <p className="break-words pt-xxs font-mono text-micro text-ink-mute">
              {failedWhileServing.error_message}
            </p>
          ) : null}
        </section>
      ) : null}

      <ServiceTabs tab={tab} onTabChange={setTab} />

      <section id={`${tab}-panel`} role="tabpanel" aria-labelledby={`${tab}-tab`} className="flex min-h-0 flex-1 flex-col">
        {tab === "logs" ? <BuildLogs deployment={selectedDeployment} /> : null}
        {tab === "advisor" ? <AdvisorSurface environmentId={service.environment_id} /> : null}
        {tab === "variables" ? <Variables serviceId={service.id} /> : null}
        {tab === "deploys" ? (
          <DeployHistory
            deployments={list}
            deploymentUrls={Object.fromEntries(
              domains
                .filter((domain) => domain.target_type === "deployment" && domain.deployment_id)
                .map((domain) => [
                  domain.deployment_id as string,
                  `${domain.tls_enabled ? "https" : "http"}://${domain.hostname}`,
                ]),
            )}
            selectedId={selectedDeployment?.id ?? null}
            onSelect={(deploymentId) => {
              setSelectedDeploymentId(deploymentId);
              setTab("logs");
            }}
            onRollback={(deploymentId) => rollback.mutate(deploymentId)}
            rollbackPending={rollback.isPending || status === "building"}
          />
        ) : null}
        {tab === "operations" ? <Operations service={service} /> : null}
        {tab === "analytics" ? <Analytics serviceId={lifecycleServiceId} /> : null}
        {tab === "service-settings" ? <ServiceSettings service={service} /> : null}
      </section>

      {!isComposeManaged && deploy.isError ? (
        <p className="border-t border-hairline px-lg py-sm text-micro text-status-failed">
          deploy request failed
        </p>
      ) : null}
      {rollback.isError ? (
        <p className="border-t border-hairline px-lg py-sm text-micro text-status-failed">
          rollback request failed
        </p>
      ) : null}
    </aside>
  );
}
