"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  useConfirmGitHubImport,
  useGitHubBranches,
  useGitHubImport,
  useGitHubImportPreview,
  useGitHubImportStatus,
  useGitHubImportTemplates,
  useGitHubInstallations,
  useGitHubRepositories,
} from "@/lib/queries";
import { ensureLocalKubernetesRuntime } from "@/lib/local-kubernetes";
import type { GitHubImportStep } from "@/lib/types";

type Addon = string;
type Stage = "source" | "repository" | "services" | "release";

const STAGES: ReadonlyArray<{ id: Stage; label: string }> = [
  { id: "source", label: "Source" },
  { id: "repository", label: "Repository" },
  { id: "services", label: "Services" },
  { id: "release", label: "Release" },
];

function Step({ step }: { step: GitHubImportStep }) {
  const tone =
    step.status === "failed"
      ? "text-status-failed"
      : step.status === "live"
        ? "text-accent"
        : "text-ink-mute";
  return (
    <li className="border-b border-hairline py-3 last:border-0">
      <div className="flex items-center justify-between gap-3 text-caption">
        <span className="text-ink">
          {step.label}
          {step.service_name ? ` · ${step.service_name}` : ""}
        </span>
        <span className={tone}>{step.status}</span>
      </div>
      {step.error_message ? (
        <p className="mt-1 text-caption text-status-failed">{step.error_message}</p>
      ) : null}
    </li>
  );
}

function StageMeter({ stage }: { stage: Stage }) {
  const activeIndex = STAGES.findIndex((entry) => entry.id === stage);
  return (
    <ol className="mt-6 grid grid-cols-4 border-y border-hairline" aria-label="Import progress">
      {STAGES.map((entry, index) => {
        const active = index === activeIndex;
        const complete = index < activeIndex;
        return (
          <li key={entry.id} className="min-w-0 py-3 text-center">
            <span
              className={[
                "mx-auto flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-medium",
                active || complete
                  ? "border-accent bg-accent text-on-accent"
                  : "border-hairline text-ink-faint",
              ].join(" ")}
              aria-hidden
            >
              {complete ? "✓" : index + 1}
            </span>
            <span className={[
              "mt-1 block truncate text-[10px]",
              active ? "text-ink" : "text-ink-faint",
            ].join(" ")}>{entry.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function FormSelect({
  children,
  label,
  value,
  onChange,
}: {
  children: React.ReactNode;
  label: string;
  value: string | number;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-caption text-ink-mute">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-sm border border-hairline bg-surface-raised px-3 py-2.5 text-caption text-ink outline-none transition-colors focus:border-accent"
      >
        {children}
      </select>
    </label>
  );
}

export function GitHubImportDialog({
  triggerClassName = "rounded-md border border-ink-faint/40 bg-surface-raised px-3 py-2 text-caption text-ink hover:border-accent hover:text-accent",
  triggerLabel = "Import from GitHub",
}: {
  triggerClassName?: string;
  triggerLabel?: string;
}) {
  const router = useRouter();
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const queryInstallation = search.get("installation_id");
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repository, setRepository] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [selectedAddons, setSelectedAddons] = useState<Addon[]>([]);
  const [selectedPublicServices, setSelectedPublicServices] = useState<string[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [importId, setImportId] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("source");
  const [isPreparingRuntime, setIsPreparingRuntime] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const status = useGitHubImportStatus();
  const templates = useGitHubImportTemplates();
  const installations = useGitHubInstallations(open && Boolean(status.data?.configured));
  const repositories = useGitHubRepositories(
    open && status.data?.configured ? installationId : null,
  );
  const branches = useGitHubBranches(
    open && status.data?.configured ? installationId : null,
    repository,
  );
  const preview = useGitHubImportPreview(
    open && status.data?.configured ? installationId : null,
    repository,
    stage === "services" || stage === "release" ? branch : null,
    templateId,
  );
  const confirm = useConfirmGitHubImport();
  const imported = useGitHubImport(importId);

  useEffect(() => {
    const requestedId = Number(queryInstallation);
    const rows = installations.data ?? [];
    if (
      Number.isSafeInteger(requestedId) &&
      requestedId > 0 &&
      rows.some((row) => row.id === requestedId)
    ) {
      setInstallationId(requestedId);
      return;
    }
    if (installationId && rows.some((row) => row.id === installationId)) return;
    setInstallationId(rows[0]?.id ?? null);
  }, [installationId, installations.data, queryInstallation]);

  useEffect(() => {
    if (
      !open ||
      !status.data?.configured ||
      installations.isLoading ||
      installations.data?.length !== 0 ||
      !status.data.install_url
    ) {
      return;
    }
    window.sessionStorage.setItem(
      "rudder:github-import-return",
      `${window.location.pathname}${window.location.search}`,
    );
    window.location.assign(status.data.install_url);
  }, [installations.data?.length, installations.isLoading, open, status.data]);

  useEffect(() => {
    if (queryInstallation) setOpen(true);
  }, [queryInstallation]);

  useEffect(() => {
    const rows = repositories.data ?? [];
    if (repository && rows.some((row) => row.full_name === repository)) return;
    setRepository(rows[0]?.full_name ?? null);
  }, [repositories.data, repository]);

  useEffect(() => {
    const rows = branches.data ?? [];
    if (branch && rows.includes(branch)) return;
    const defaultBranch = repositories.data?.find(
      (row) => row.full_name === repository,
    )?.default_branch;
    setBranch(rows.includes(defaultBranch ?? "") ? defaultBranch ?? null : rows[0] ?? null);
  }, [branch, branches.data, repositories.data, repository]);

  useEffect(() => {
    if (preview.data?.compose_source !== "generated") {
      setSelectedAddons([]);
      return;
    }
    const template = templates.data?.find((entry) => entry.id === templateId);
    const suggested = template?.addons ?? preview.data.addons;
    setSelectedAddons(suggested.filter((addon) => preview.data?.addons.includes(addon)));
  }, [preview.data, templateId, templates.data]);

  useEffect(() => {
    setSelectedPublicServices(
      (preview.data?.services ?? [])
        .filter((service) => service.is_public && service.role === "web")
        .map((service) => service.name),
    );
  }, [preview.data]);

  const canContinueRepository = Boolean(installationId && repository && branch);
  const canConfirm = Boolean(
    installationId &&
      repository &&
      branch &&
      preview.data &&
      preview.data.services.some(
        (service) => service.role === "web" && selectedPublicServices.includes(service.name),
      ) &&
      !isPreparingRuntime &&
      !confirm.isPending,
  );

  function reset() {
    setRepository(null);
    setBranch(null);
    setSelectedAddons([]);
    setSelectedPublicServices([]);
    setTemplateId(null);
    setImportId(null);
    setStage("source");
    setIsPreparingRuntime(false);
    setBootstrapError(null);
    confirm.reset();
  }

  function toggleAddon(addon: Addon) {
    setSelectedAddons((current) =>
      current.includes(addon) ? current.filter((item) => item !== addon) : [...current, addon],
    );
  }

  function togglePublicService(name: string) {
    setSelectedPublicServices((current) =>
      current.includes(name) ? current.filter((entry) => entry !== name) : [...current, name],
    );
  }

  async function startImport() {
    if (!installationId || !repository || !branch) return;
    setBootstrapError(null);
    setIsPreparingRuntime(true);
    try {
      await ensureLocalKubernetesRuntime();
      const created = await confirm.mutateAsync({
        installationId,
        repository,
        branch,
        addons: selectedAddons,
        templateId,
        publicServices: selectedPublicServices,
      });
      setImportId(created.import_id);
    } catch (error) {
      setBootstrapError(
        error instanceof Error ? error.message : "Could not prepare the local Kubernetes runtime.",
      );
    } finally {
      setIsPreparingRuntime(false);
    }
  }

  const sourceTitle = templateId
    ? templates.data?.find((template) => template.id === templateId)?.name ?? "Starter template"
    : "Repository Compose";

  return (
    <>
      <button className={triggerClassName} onClick={() => setOpen(true)}>
        {triggerLabel}
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-surface/80 p-4 backdrop-blur-sm sm:p-6">
          <section
            aria-modal="true"
            aria-label="Import from GitHub"
            role="dialog"
            className="w-full min-w-0 max-w-2xl rounded-lg border border-hairline bg-surface-raised shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4 px-5 pb-0 pt-5 sm:px-7 sm:pt-7">
              <div>
                <p className="text-heading">Import from GitHub</p>
                <p className="mt-1 max-w-xl text-caption text-ink-mute">
                  Review the exact Compose release before Rudder creates any infrastructure.
                </p>
              </div>
              <button
                className="rounded-xs px-xs py-xxs text-ink-faint transition-colors hover:text-ink"
                onClick={() => {
                  reset();
                  setOpen(false);
                }}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {importId ? (
              <div className="px-5 pb-5 pt-6 sm:px-7 sm:pb-7">
                <div className="border border-hairline bg-surface px-4 py-4">
                  <p className="text-caption text-ink">
                    Provisioning {imported.data?.repository ?? repository}.
                  </p>
                  <p className="mt-1 text-micro text-ink-mute">
                    Every service below shares one Compose release and its build log.
                  </p>
                  <ul className="mt-3">
                    {imported.data?.steps.map((step) => <Step key={step.service_id} step={step} />)}
                  </ul>
                  {imported.isError ? (
                    <p className="mt-3 text-caption text-status-failed">
                      Could not load import progress. Reopen the project to check the release.
                    </p>
                  ) : null}
                  {imported.data ? (
                    <button
                      className="mt-4 rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep"
                      onClick={() =>
                        router.push(
                          `/projects/${imported.data.project_id}/environments/${imported.data.environment_id}`,
                        )
                      }
                    >
                      Open imported project
                    </button>
                  ) : null}
                </div>
              </div>
            ) : (
              <>
                <StageMeter stage={stage} />
                <div className="min-h-[22rem] px-5 py-6 sm:px-7">
                  {status.isLoading ? (
                    <p className="text-caption text-ink-mute">Checking GitHub App setup…</p>
                  ) : null}
                  {status.isError ? (
                    <p className="text-caption text-status-failed">
                      Could not check GitHub App setup. Refresh and try again.
                    </p>
                  ) : null}
                  {status.data && !status.data.configured ? (
                    <div className="max-w-lg border border-status-failed/30 bg-status-failed/5 px-4 py-4 text-caption text-ink-mute">
                      <p className="font-medium text-ink">GitHub import is not enabled here.</p>
                      <p className="mt-1">
                        A workspace operator must configure the Rudder GitHub App before repositories can be imported.
                      </p>
                    </div>
                  ) : null}

                  {status.data?.configured && stage === "source" ? (
                    <div>
                      <p className="text-micro text-ink-faint">Step 1 of 4</p>
                      <h2 className="mt-2 text-heading-md text-ink">Choose a source</h2>
                      <p className="mt-1 max-w-lg text-caption text-ink-mute">
                        Rudder always prefers a repository Compose file. Choose a reviewed starter only when the repository has no Compose definition.
                      </p>
                      <div className="mt-6 grid gap-px overflow-hidden border border-hairline bg-hairline sm:grid-cols-2">
                        <button
                          type="button"
                          onClick={() => setTemplateId(null)}
                          className={[
                            "bg-surface px-4 py-4 text-left transition-colors hover:bg-surface-soft",
                            templateId === null ? "bg-accent/10" : "",
                          ].join(" ")}
                        >
                          <span className="text-caption font-medium text-ink">Repository Compose</span>
                          <span className="mt-1 block text-micro text-ink-mute">
                            Use compose.yaml from the selected branch whenever it exists.
                          </span>
                        </button>
                        {(templates.data ?? []).map((template) => (
                          <button
                            key={template.id}
                            type="button"
                            onClick={() => setTemplateId(template.id)}
                            className={[
                              "bg-surface px-4 py-4 text-left transition-colors hover:bg-surface-soft",
                              templateId === template.id ? "bg-accent/10" : "",
                            ].join(" ")}
                          >
                            <span className="text-caption font-medium text-ink">{template.name}</span>
                            <span className="mt-1 block text-micro text-ink-mute">{template.description}</span>
                          </button>
                        ))}
                      </div>
                      <div className="mt-6 flex justify-end">
                        <button
                          type="button"
                          onClick={() => setStage("repository")}
                          className="rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep"
                        >
                          Next: repository
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {status.data?.configured && stage === "repository" ? (
                    <div>
                      <p className="text-micro text-ink-faint">Step 2 of 4</p>
                      <h2 className="mt-2 text-heading-md text-ink">Select repository</h2>
                      <p className="mt-1 max-w-lg text-caption text-ink-mute">
                        Choose the installation, repository, and branch whose manifest Rudder should inspect.
                      </p>
                      <div className="mt-6 space-y-4">
                        {installations.isLoading ? <p className="text-caption text-ink-mute">Finding your GitHub connection…</p> : null}
                        {installations.isError ? <p className="text-caption text-status-failed">Could not load GitHub connections.</p> : null}
                        {installations.data?.length === 0 ? <p className="text-caption text-ink-mute">Redirecting to GitHub to connect your repositories…</p> : null}
                        {(installations.data?.length ?? 0) > 0 ? (
                          <FormSelect
                            label="GitHub connection"
                            value={installationId ?? ""}
                            onChange={(value) => {
                              setInstallationId(Number(value) || null);
                              setRepository(null);
                              setBranch(null);
                            }}
                          >
                            {(installations.data ?? []).map((row) => (
                              <option key={row.id} value={row.id}>
                                {row.account_login} · {row.repository_selection === "all" ? "all repositories" : "selected repositories"}
                              </option>
                            ))}
                          </FormSelect>
                        ) : null}
                        {installationId ? (
                          <FormSelect
                            label="Repository"
                            value={repository ?? ""}
                            onChange={(value) => {
                              setRepository(value || null);
                              setBranch(null);
                            }}
                          >
                            <option value="">Choose a repository</option>
                            {(repositories.data ?? []).map((row) => (
                              <option key={row.full_name} value={row.full_name}>
                                {row.full_name}{row.private ? " · private" : ""}
                              </option>
                            ))}
                          </FormSelect>
                        ) : null}
                        {repositories.isLoading ? <p className="text-caption text-ink-mute">Loading repositories…</p> : null}
                        {repositories.isError ? <p className="text-caption text-status-failed">Could not load repositories for this connection.</p> : null}
                        {repository ? (
                          <FormSelect label="Branch" value={branch ?? ""} onChange={(value) => setBranch(value || null)}>
                            {(branches.data ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
                          </FormSelect>
                        ) : null}
                      </div>
                      <div className="mt-6 flex items-center justify-between gap-3">
                        <button type="button" onClick={() => setStage("source")} className="rounded-sm border border-hairline px-lg py-sm text-button text-ink hover:border-hairline-strong">Back</button>
                        <button type="button" disabled={!canContinueRepository} onClick={() => setStage("services")} className="rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40">Next: review services</button>
                      </div>
                    </div>
                  ) : null}

                  {status.data?.configured && stage === "services" ? (
                    <div>
                      <p className="text-micro text-ink-faint">Step 3 of 4</p>
                      <h2 className="mt-2 text-heading-md text-ink">Review detected services</h2>
                      <p className="mt-1 max-w-lg text-caption text-ink-mute">Detection is evidence, not infrastructure. Confirm the roles and private dependencies before a release is created.</p>
                      {preview.isLoading ? <p className="mt-6 text-caption text-ink-mute">Inspecting the selected branch…</p> : null}
                      {preview.isError ? <p className="mt-6 text-caption text-status-failed">Could not inspect this repository. Check the branch and try again.</p> : null}
                      {preview.data ? (
                        <div className="mt-6 space-y-5">
                          <div className="border border-hairline bg-surface px-4 py-4">
                            <p className="text-caption font-medium text-ink">{preview.data.compose_source === "repository" ? "Repository Compose detected" : "Generated Compose proposal"}</p>
                            <p className="mt-1 text-micro text-ink-mute">{preview.data.compose_source === "repository" ? "The repository manifest remains authoritative." : `${sourceTitle} supplies a reviewable starting point for this Node application.`}</p>
                          </div>
                          {preview.data.processes.length ? (
                            <div>
                              <p className="text-caption font-medium text-ink">Detected processes</p>
                              <ul className="mt-2 divide-y divide-hairline border-y border-hairline">
                                {preview.data.processes.map((process) => <li key={`${process.role}-${process.command}`} className="flex items-center justify-between gap-3 py-2 text-caption"><span className="text-ink">{process.role}</span><code className="truncate text-micro text-ink-mute">{process.command}</code></li>)}
                              </ul>
                            </div>
                          ) : null}
                          {preview.data.compose_source === "generated" ? (
                            <div>
                              <p className="text-caption font-medium text-ink">Private add-ons</p>
                              <div className="mt-2 space-y-2">
                                {preview.data.addons.map((addon) => <label key={addon} className="flex items-center gap-2 text-caption text-ink"><input type="checkbox" checked={selectedAddons.includes(addon)} onChange={() => toggleAddon(addon)} />Provision private {addon}</label>)}
                                {preview.data.externally_managed.map((addon) => <p key={addon} className="text-micro text-ink-mute">{addon} already has an external connection and will not be provisioned.</p>)}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="mt-6 flex items-center justify-between gap-3"><button type="button" onClick={() => setStage("repository")} className="rounded-sm border border-hairline px-lg py-sm text-button text-ink hover:border-hairline-strong">Back</button><button type="button" disabled={!preview.data} onClick={() => setStage("release")} className="rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40">Next: release summary</button></div>
                    </div>
                  ) : null}

                  {status.data?.configured && stage === "release" ? (
                    <div>
                      <p className="text-micro text-ink-faint">Step 4 of 4</p>
                      <h2 className="mt-2 text-heading-md text-ink">Confirm the release</h2>
                      <p className="mt-1 max-w-lg text-caption text-ink-mute">Only checked services receive a public URL. All others stay on Rudder&apos;s private network.</p>
                      {preview.data ? (
                        <div className="mt-6 space-y-5">
                          <div>
                            <p className="text-caption font-medium text-ink">Public URLs</p>
                            <ul className="mt-2 divide-y divide-hairline border-y border-hairline">
                              {preview.data.services.map((service) => <li key={service.name} className="flex items-center justify-between gap-3 py-2 text-caption"><div><p className="font-medium text-ink">{service.name}</p><p className="text-micro text-ink-mute">{service.role}{service.container_port ? ` · :${service.container_port}` : ""}</p></div>{service.is_public ? <label className="flex shrink-0 items-center gap-2 text-accent"><input type="checkbox" checked={selectedPublicServices.includes(service.name)} onChange={() => togglePublicService(service.name)} />Public</label> : <span className="text-micro text-ink-faint">Private</span>}</li>)}
                            </ul>
                          </div>
                          <details className="border border-hairline bg-surface px-3 py-2">
                            <summary className="cursor-pointer text-caption text-ink">View resolved Compose manifest</summary>
                            <pre className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap break-words border-t border-hairline pt-3 font-mono text-[11px] leading-5 text-ink-mute">{preview.data.compose_manifest}</pre>
                          </details>
                        </div>
                      ) : <p className="mt-6 text-caption text-status-failed">The release preview is unavailable. Return to services and try again.</p>}
                      <div className="mt-6 flex items-center justify-between gap-3"><button type="button" onClick={() => setStage("services")} className="rounded-sm border border-hairline px-lg py-sm text-button text-ink hover:border-hairline-strong">Back</button><button type="button" disabled={!canConfirm} onClick={() => void startImport()} className="rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40">{isPreparingRuntime ? "Preparing local Kubernetes…" : confirm.isPending ? "Creating release…" : "Confirm and deploy"}</button></div>
                      {bootstrapError ? <p className="mt-3 text-caption text-status-failed">{bootstrapError}</p> : null}
                      {confirm.isError ? <p className="mt-3 text-caption text-status-failed">{confirm.error.message}</p> : null}
                    </div>
                  ) : null}
                </div>
              </>
            )}
          </section>
        </div>
      ) : null}
    </>
  );
}
