"use client";

import { useEffect, useState } from "react";

import { useDeploy, useDeployments, useInstances } from "@/lib/queries";
import { deriveServiceStatus, latestDeployment } from "@/lib/status";
import type { Service } from "@/lib/types";

import { BuildLogs } from "./build-logs";
import { DeployHistory } from "./deploy-history";
import { StatusDot } from "./status-dot";
import { Variables } from "./variables";

type Tab = "logs" | "variables" | "deploys";

const TABS: readonly { id: Tab; label: string }[] = [
  { id: "logs", label: "Build logs" },
  { id: "variables", label: "Variables" },
  { id: "deploys", label: "Deploys" },
];

export function DetailPanel({
  service,
  url,
  managedByServiceId,
  onClose,
}: {
  service: Service;
  url: string | null;
  managedByServiceId?: string;
  onClose: () => void;
}) {
  const lifecycleServiceId = managedByServiceId ?? service.id;
  const isComposeManaged = managedByServiceId !== undefined;
  const deployments = useDeployments(lifecycleServiceId);
  const instances = useInstances(lifecycleServiceId);
  const deploy = useDeploy(service.id);

  const [tab, setTab] = useState<Tab>("logs");
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<string | null>(null);

  // A different service means a different deploy history.
  useEffect(() => {
    setSelectedDeploymentId(null);
    setTab("logs");
  }, [service.id]);

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
    <aside className="flex w-[26rem] shrink-0 flex-col border-l border-hairline bg-surface-soft">
      <div className="flex items-start justify-between gap-md border-b border-hairline px-lg py-md">
        <div className="min-w-0">
          <div className="flex items-center gap-sm">
            <h2 className="truncate text-heading-md text-ink">{service.name}</h2>
            <StatusDot status={status} />
          </div>
          <p className="truncate pt-xxs text-micro text-ink-mute">
            {service.source_repo ? (
              <span className="font-mono">
                {service.source_repo}
                {service.source_branch ? `@${service.source_branch}` : ""}
              </span>
            ) : (
              <span>{service.kind}</span>
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
          <button
            type="button"
            onClick={() => deploy.mutate()}
            disabled={deploy.isPending || status === "building"}
            className="rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {status === "building" || deploy.isPending ? "Deploying…" : "Deploy"}
          </button>
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

      <div className="flex shrink-0 items-center gap-lg border-b border-hairline px-lg">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setTab(entry.id)}
            className={[
              "-mb-px border-b py-sm text-micro transition-colors",
              tab === entry.id
                ? "border-ink text-ink"
                : "border-transparent text-ink-mute hover:text-ink-secondary",
            ].join(" ")}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "logs" ? <BuildLogs deployment={selectedDeployment} /> : null}
      {tab === "variables" ? <Variables serviceId={service.id} /> : null}
      {tab === "deploys" ? (
        <DeployHistory
          deployments={list}
          selectedId={selectedDeployment?.id ?? null}
          onSelect={(deploymentId) => {
            setSelectedDeploymentId(deploymentId);
            setTab("logs");
          }}
        />
      ) : null}

      {!isComposeManaged && deploy.isError ? (
        <p className="border-t border-hairline px-lg py-sm text-micro text-status-failed">
          deploy request failed
        </p>
      ) : null}
    </aside>
  );
}
