"use client";

import { useMemo, useState } from "react";

import {
  useAutoscalingOperation,
  useBackupOperation,
  useDeleteScheduleOperation,
  useDeployments,
  useJobOperation,
  useObservabilityOperation,
  useOperationRollback,
  usePlacementOperation,
  useReadReplicasOperation,
  useResourcesOperation,
  useRolloutOperation,
  useScaleOperation,
  useScheduleOperation,
  useServiceOperations,
  useStorageOperation,
} from "@/lib/queries";
import type { OperationStatus, Service, ServiceOperation } from "@/lib/types";

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : {};
}

function number(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Operation request failed. Reload and retry.";
}

const statusClass: Record<OperationStatus, string> = {
  pending: "text-status-building",
  progressing: "text-status-building",
  healthy: "text-status-live",
  degraded: "text-status-building",
  failed: "text-status-failed",
  cancelled: "text-ink-faint",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-hairline px-lg py-md">
      <h3 className="text-micro font-medium text-ink">{title}</h3>
      <div className="pt-sm">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-micro text-ink-mute">
      <span className="mb-xxs block">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-sm border border-hairline-strong bg-surface-inset px-sm py-xs font-mono text-micro text-ink placeholder:text-ink-faint";
const buttonClass =
  "rounded-sm border border-hairline-strong px-sm py-xs text-micro text-ink hover:border-ink-faint disabled:cursor-not-allowed disabled:opacity-50";

function OperationHistory({ history }: { history: ServiceOperation[] }) {
  if (history.length === 0) return <p className="text-micro text-ink-faint">No operations requested.</p>;
  return (
    <ul className="space-y-xs" aria-label="Operation history">
      {history.slice(0, 8).map((operation) => (
        <li key={operation.id} className="border-b border-hairline-faint pb-xs text-micro">
          <div className="flex items-center justify-between gap-sm">
            <span className="font-mono text-ink-secondary">{operation.kind.replaceAll("_", " ")}</span>
            <span className={statusClass[operation.status]}>{operation.status}</span>
          </div>
          {operation.error_message ? (
            <p className="pt-xxs text-status-failed">{operation.error_message}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/**
 * Controls only express declarative intent. The control plane records it first,
 * then the Kubernetes reconciler reports what was actually applied. No control
 * here treats a desired value as proof that a workload is healthy.
 */
export function Operations({ service }: { service: Service }) {
  const operations = useServiceOperations(service.id);
  const deployments = useDeployments(service.id);
  const scale = useScaleOperation(service.id);
  const resources = useResourcesOperation(service.id);
  const autoscaling = useAutoscalingOperation(service.id);
  const placement = usePlacementOperation(service.id);
  const rollout = useRolloutOperation(service.id);
  const rollback = useOperationRollback(service.id);
  const backup = useBackupOperation(service.id);
  const replicas = useReadReplicasOperation(service.id);
  const storage = useStorageOperation(service.id);
  const schedule = useScheduleOperation(service.id);
  const runJob = useJobOperation(service.id);
  const observability = useObservabilityOperation(service.id);
  const deleteSchedule = useDeleteScheduleOperation(service.id);

  const desired = operations.data?.desired ?? {};
  const observed = operations.data?.observed ?? {};
  const desiredResources = record(desired.resources);
  const desiredAutoscaling = record(desired.autoscaling);
  const desiredPlacement = record(desired.placement);
  const desiredRollout = record(desired.rollout);
  const desiredObservability = record(desired.observability);
  const runtime = record(observed.runtime);
  const reconciliation = record(observed.reconciliation);
  const isApp = service.kind === "app";
  const capabilities = operations.data?.capabilities;
  const databaseEngine = capabilities?.database_engine ?? null;
  const managedDatabase = service.kind === "database" && databaseEngine !== null;
  const sqlDatabase = managedDatabase && ["postgres", "mysql", "mariadb"].includes(databaseEngine);
  const jobCommandsAvailable = isApp && Boolean(capabilities?.job_commands_available);

  const [replicaValue, setReplicaValue] = useState(String(number(desired.replicas, service.replica_count)));
  const [cpuRequest, setCpuRequest] = useState(text(desiredResources.cpu_request));
  const [cpuLimit, setCpuLimit] = useState(text(desiredResources.cpu_limit, String(service.cpu_limit)));
  const [memoryRequest, setMemoryRequest] = useState(text(desiredResources.memory_request_mb));
  const [memoryLimit, setMemoryLimit] = useState(text(desiredResources.memory_limit_mb, String(service.memory_limit_mb)));
  const [autoscaleMin, setAutoscaleMin] = useState(String(number(desiredAutoscaling.min_replicas, 1)));
  const [autoscaleMax, setAutoscaleMax] = useState(String(number(desiredAutoscaling.max_replicas, 3)));
  const [rolloutStrategy, setRolloutStrategy] = useState<"rolling" | "blue_green" | "canary">(
    text(desiredRollout.strategy, "rolling") as "rolling" | "blue_green" | "canary",
  );
  const [canarySteps, setCanarySteps] = useState(
    Array.isArray(desiredRollout.canary_steps) ? desiredRollout.canary_steps.join(",") : "25,50,100",
  );
  const [nodeSelector, setNodeSelector] = useState(
    Object.entries(record(desiredPlacement.node_selector))
      .map(([key, value]) => `${key}=${String(value)}`)
      .join(","),
  );
  const [topologySpread, setTopologySpread] = useState(Boolean(desiredPlacement.topology_spread));
  const [antiAffinity, setAntiAffinity] = useState(Boolean(desiredPlacement.anti_affinity));
  const [retentionDays, setRetentionDays] = useState("7");
  const [readReplicas, setReadReplicas] = useState("1");
  const [storageCurrent, setStorageCurrent] = useState("");
  const [storageRequested, setStorageRequested] = useState("");
  const [jobCommand, setJobCommand] = useState("");
  const [scheduleCron, setScheduleCron] = useState("0 * * * *");
  const [scheduleCommand, setScheduleCommand] = useState("");
  const [prometheus, setPrometheus] = useState(Boolean(desiredObservability.prometheus));
  const [grafana, setGrafana] = useState(Boolean(desiredObservability.grafana));
  const [restoreCandidate, setRestoreCandidate] = useState<string | null>(null);

  const knownGoodDeployments = useMemo(
    () => (deployments.data ?? []).filter((deployment) => deployment.status === "live" || deployment.status === "superseded"),
    [deployments.data],
  );
  const schedules = Array.isArray(desired.schedules) ? desired.schedules : [];
  const mutationError = [
    scale.error,
    resources.error,
    autoscaling.error,
    placement.error,
    rollout.error,
    rollback.error,
    backup.error,
    replicas.error,
    storage.error,
    schedule.error,
    runJob.error,
    observability.error,
    deleteSchedule.error,
  ].find(Boolean);

  if (operations.isLoading) return <div className="px-lg py-md text-micro text-ink-faint">Loading operations…</div>;
  if (operations.isError) return <div className="px-lg py-md text-micro text-status-failed">{errorText(operations.error)}</div>;

  const observedStatus = text(record(runtime.workload).status, text(reconciliation.status, "unknown"));

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto" aria-label="Service operations">
      <section className="border-b border-hairline bg-surface-inset px-lg py-sm" aria-live="polite">
        <div className="flex items-center justify-between gap-sm text-micro">
          <span className="text-ink-secondary">Observed Kubernetes state</span>
          <span className={observedStatus === "healthy" ? "text-status-live" : "text-ink-mute"}>{observedStatus}</span>
        </div>
        <p className="pt-xxs text-micro text-ink-faint">
          {operations.data?.pending_reconciliation ? "Changes are waiting for reconciliation." : "Desired state is reconciled from the cluster."}
        </p>
      </section>

      {isApp ? (
        <>
          <Section title="Run">
            <div className="grid grid-cols-2 gap-sm">
              <Field label="Manual replicas">
                <input aria-label="Manual replicas" className={inputClass} inputMode="numeric" value={replicaValue} onChange={(event) => setReplicaValue(event.target.value)} />
              </Field>
              <div className="flex items-end">
                <button type="button" className={buttonClass} disabled={scale.isPending} onClick={() => scale.mutate(Number(replicaValue))}>Apply scale</button>
              </div>
            </div>
            <div className="mt-sm grid grid-cols-2 gap-sm">
              <Field label="CPU request"><input aria-label="CPU request" className={inputClass} placeholder="500m" value={cpuRequest} onChange={(event) => setCpuRequest(event.target.value)} /></Field>
              <Field label="CPU limit"><input aria-label="CPU limit" className={inputClass} placeholder="1" value={cpuLimit} onChange={(event) => setCpuLimit(event.target.value)} /></Field>
              <Field label="Memory request (MB)"><input aria-label="Memory request" className={inputClass} inputMode="numeric" value={memoryRequest} onChange={(event) => setMemoryRequest(event.target.value)} /></Field>
              <Field label="Memory limit (MB)"><input aria-label="Memory limit" className={inputClass} inputMode="numeric" value={memoryLimit} onChange={(event) => setMemoryLimit(event.target.value)} /></Field>
            </div>
            <button type="button" className={`${buttonClass} mt-sm`} disabled={resources.isPending} onClick={() => resources.mutate({ cpu_request: cpuRequest || undefined, cpu_limit: cpuLimit || undefined, memory_request_mb: memoryRequest ? Number(memoryRequest) : undefined, memory_limit_mb: memoryLimit ? Number(memoryLimit) : undefined })}>Save resources</button>
            <div className="mt-md border-t border-hairline-faint pt-sm">
              <p className="text-micro text-ink-secondary">Autoscaling</p>
              <div className="mt-xs grid grid-cols-2 gap-sm"><Field label="Minimum"><input aria-label="Minimum replicas" className={inputClass} inputMode="numeric" value={autoscaleMin} onChange={(event) => setAutoscaleMin(event.target.value)} /></Field><Field label="Maximum"><input aria-label="Maximum replicas" className={inputClass} inputMode="numeric" value={autoscaleMax} onChange={(event) => setAutoscaleMax(event.target.value)} /></Field></div>
              <button type="button" className={`${buttonClass} mt-sm`} disabled={autoscaling.isPending} onClick={() => autoscaling.mutate({ min_replicas: Number(autoscaleMin), max_replicas: Number(autoscaleMax), target_cpu_percent: 80 })}>Apply autoscaling</button>
              <p className="pt-xs text-micro text-ink-faint">Autoscaling and manual replica intent are mutually exclusive in Kubernetes.</p>
            </div>
          </Section>

          <Section title="Release">
            <div className="grid grid-cols-[1fr_auto] gap-sm"><Field label="Rollout strategy"><select aria-label="Rollout strategy" className={inputClass} value={rolloutStrategy} onChange={(event) => setRolloutStrategy(event.target.value as "rolling" | "blue_green" | "canary")}><option value="rolling">rolling</option><option value="blue_green">blue/green</option><option value="canary">canary</option></select></Field><div className="flex items-end"><button type="button" className={buttonClass} disabled={rollout.isPending} onClick={() => rollout.mutate({ strategy: rolloutStrategy, canary_steps: rolloutStrategy === "canary" ? canarySteps.split(",").map((step) => Number(step.trim())).filter(Boolean) : undefined })}>Save rollout</button></div></div>
            {rolloutStrategy === "canary" ? <Field label="Canary steps (%)"><input aria-label="Canary steps" className={`${inputClass} mt-sm`} value={canarySteps} onChange={(event) => setCanarySteps(event.target.value)} /></Field> : null}
            <div className="mt-md border-t border-hairline-faint pt-sm">
              <p className="text-micro text-ink-secondary">Restore immutable release</p>
              <p className="pt-xxs text-micro text-ink-faint">
                Restoring a release repoints the existing immutable image. No source build is started.
              </p>
              <div className="mt-sm space-y-xs">
                {knownGoodDeployments.map((deployment) => (
                  <div key={deployment.id} className="flex items-center justify-between gap-sm">
                    <span className="truncate font-mono text-micro text-ink-mute">
                      {deployment.commit_sha ?? deployment.image_tag ?? deployment.id}
                    </span>
                    {restoreCandidate === deployment.id ? (
                      <div className="flex items-center gap-xs">
                        <button
                          type="button"
                          className={buttonClass}
                          onClick={() => setRestoreCandidate(null)}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className={buttonClass}
                          disabled={rollback.isPending}
                          onClick={() => {
                            rollback.mutate(deployment.id);
                            setRestoreCandidate(null);
                          }}
                        >
                          Confirm restore without a build
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className={buttonClass}
                        disabled={rollback.isPending}
                        onClick={() => setRestoreCandidate(deployment.id)}
                      >
                        Restore
                      </button>
                    )}
                  </div>
                ))}
                {knownGoodDeployments.length === 0 ? (
                  <p className="text-micro text-ink-faint">No immutable healthy release is available.</p>
                ) : null}
              </div>
            </div>
          </Section>

          <Section title="Jobs & placement">
            <Field label="Node selector (key=value, comma separated)"><input aria-label="Node selector" className={inputClass} value={nodeSelector} onChange={(event) => setNodeSelector(event.target.value)} /></Field>
            <div className="mt-sm flex gap-md text-micro text-ink-mute"><label><input type="checkbox" checked={topologySpread} onChange={(event) => setTopologySpread(event.target.checked)} /> spread across nodes</label><label><input type="checkbox" checked={antiAffinity} onChange={(event) => setAntiAffinity(event.target.checked)} /> anti-affinity</label></div>
            <button type="button" className={`${buttonClass} mt-sm`} disabled={placement.isPending} onClick={() => { const selector = Object.fromEntries(nodeSelector.split(",").map((part) => part.trim()).filter(Boolean).map((part) => { const [key, ...value] = part.split("="); return [key.trim(), value.join("=").trim()]; })); placement.mutate({ node_selector: selector, topology_spread: topologySpread, anti_affinity: antiAffinity }); }}>Apply placement</button>
            {jobCommandsAvailable ? (
              <>
                <div className="mt-md border-t border-hairline-faint pt-sm"><Field label="One-off command (must be approved by the service template)"><input aria-label="One-off command" className={inputClass} placeholder="npm run migrate" value={jobCommand} onChange={(event) => setJobCommand(event.target.value)} /></Field><button type="button" className={`${buttonClass} mt-sm`} disabled={runJob.isPending || !jobCommand.trim()} onClick={() => runJob.mutate({ command: jobCommand.trim().split(/\s+/) })}>Run job</button></div>
                <div className="mt-md border-t border-hairline-faint pt-sm"><Field label="Schedule"><input aria-label="Schedule cron" className={inputClass} value={scheduleCron} onChange={(event) => setScheduleCron(event.target.value)} /></Field><Field label="Scheduled command"><input aria-label="Scheduled command" className={`${inputClass} mt-sm`} placeholder="npm run cleanup" value={scheduleCommand} onChange={(event) => setScheduleCommand(event.target.value)} /></Field><button type="button" className={`${buttonClass} mt-sm`} disabled={schedule.isPending || !scheduleCommand.trim()} onClick={() => schedule.mutate({ cron: scheduleCron, command: scheduleCommand.trim().split(/\s+/) })}>Add schedule</button>{schedules.map((item) => { const entry = record(item); return <div key={String(entry.operation_id)} className="mt-xs flex justify-between text-micro text-ink-mute"><span>{text(record(entry.spec).cron, "schedule")}</span><button type="button" className="text-ink-faint hover:text-status-failed" onClick={() => deleteSchedule.mutate(String(entry.operation_id))}>remove</button></div>; })}</div>
              </>
            ) : <p className="mt-md border-t border-hairline-faint pt-sm text-micro text-ink-faint">No approved one-off or scheduled commands are configured for this service.</p>}
          </Section>
        </>
      ) : null}

      {managedDatabase ? <Section title="Data"><p className="text-micro text-ink-faint">Managed {databaseEngine} controls. Unsupported operator actions are reported as degraded instead of being treated as successful.</p>{sqlDatabase ? <div className="mt-sm grid grid-cols-2 gap-sm"><Field label="Backup retention (days)"><input aria-label="Backup retention days" className={inputClass} inputMode="numeric" value={retentionDays} onChange={(event) => setRetentionDays(event.target.value)} /></Field><div className="flex items-end"><button type="button" className={buttonClass} disabled={backup.isPending} onClick={() => backup.mutate(Number(retentionDays))}>Create backup</button></div><Field label="Read replicas"><input aria-label="Read replicas" className={inputClass} inputMode="numeric" value={readReplicas} onChange={(event) => setReadReplicas(event.target.value)} /></Field><div className="flex items-end"><button type="button" className={buttonClass} disabled={replicas.isPending} onClick={() => replicas.mutate(Number(readReplicas))}>Request replicas</button></div></div> : <p className="mt-sm text-micro text-ink-faint">Backups and SQL read replicas are unavailable for this engine.</p>}<div className="mt-sm grid grid-cols-2 gap-sm"><Field label="Current storage (MB)"><input aria-label="Current storage" className={inputClass} inputMode="numeric" value={storageCurrent} onChange={(event) => setStorageCurrent(event.target.value)} /></Field><Field label="Requested storage (MB)"><input aria-label="Requested storage" className={inputClass} inputMode="numeric" value={storageRequested} onChange={(event) => setStorageRequested(event.target.value)} /></Field></div><button type="button" className={`${buttonClass} mt-sm`} disabled={storage.isPending || !storageCurrent || !storageRequested} onClick={() => storage.mutate({ currentSizeMb: Number(storageCurrent), requestedSizeMb: Number(storageRequested) })}>Request storage expansion</button><p className="pt-xs text-micro text-ink-faint">Volumes can grow but cannot safely shrink. Read replicas always remain private.</p></Section> : <Section title="Data"><p className="text-micro text-ink-faint">Data controls are unavailable until Rudder confirms managed database capability for this service.</p></Section>}

      <Section title="Observability"><div className="flex gap-md text-micro text-ink-mute"><label><input aria-label="Enable Prometheus" type="checkbox" checked={prometheus} onChange={(event) => setPrometheus(event.target.checked)} /> Prometheus</label><label><input aria-label="Enable Grafana" type="checkbox" checked={grafana} onChange={(event) => setGrafana(event.target.checked)} /> Grafana</label></div><button type="button" className={`${buttonClass} mt-sm`} disabled={observability.isPending} onClick={() => observability.mutate({ prometheus, grafana })}>Save observability</button></Section>
      <Section title="Operation history"><OperationHistory history={operations.data?.history ?? []} /></Section>
      {mutationError ? <p role="alert" className="px-lg py-sm text-micro text-status-failed">{errorText(mutationError)}</p> : null}
    </div>
  );
}
