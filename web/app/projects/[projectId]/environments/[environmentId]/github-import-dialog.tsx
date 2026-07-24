"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  useConfirmGitHubImport,
  useGitHubBranches,
  useGitHubImport,
  useGitHubImportPreview,
  useGitHubImportStatus,
  useGitHubInstallations,
  useGitHubRepositories,
} from "@/lib/queries";
import type { GitHubImportStep } from "@/lib/types";

type Addon = "postgres" | "redis";

function stepLabel(step: GitHubImportStep): string {
  if (step.status === "live") return "live";
  if (step.status === "failed") return "failed";
  if (step.status === "superseded") return "superseded";
  return step.status;
}

function Step({ step }: { step: GitHubImportStep }) {
  const tone = step.status === "failed" ? "text-status-failed" : step.status === "live" ? "text-accent" : "text-ink-mute";
  return (
    <li className="border-b border-hairline py-3 last:border-0">
      <div className="flex items-center justify-between gap-3 text-caption">
        <span className="text-ink">{step.label}{step.service_name ? ` · ${step.service_name}` : ""}</span>
        <span className={tone}>{stepLabel(step)}</span>
      </div>
      {step.error_message ? <p className="mt-1 text-caption text-status-failed">{step.error_message}</p> : null}
    </li>
  );
}

export function GitHubImportDialog() {
  const router = useRouter();
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const queryInstallation = search.get("installation_id");
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repository, setRepository] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [selectedAddons, setSelectedAddons] = useState<Addon[]>([]);
  const [importId, setImportId] = useState<string | null>(null);
  const [stage, setStage] = useState<"source" | "review">("source");

  const status = useGitHubImportStatus();
  const installations = useGitHubInstallations(open && Boolean(status.data?.configured));
  const repositories = useGitHubRepositories(open && status.data?.configured ? installationId : null);
  const branches = useGitHubBranches(open && status.data?.configured ? installationId : null, repository);
  const preview = useGitHubImportPreview(
    open && status.data?.configured ? installationId : null,
    repository,
    stage === "review" ? branch : null,
  );
  const confirm = useConfirmGitHubImport();
  const imported = useGitHubImport(importId);

  useEffect(() => {
    const requestedId = Number(queryInstallation);
    const rows = installations.data ?? [];
    if (Number.isSafeInteger(requestedId) && requestedId > 0 && rows.some((row) => row.id === requestedId)) {
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
    ) return;
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
    const defaultBranch = repositories.data?.find((row) => row.full_name === repository)?.default_branch;
    setBranch(rows.includes(defaultBranch ?? "") ? defaultBranch ?? null : rows[0] ?? null);
  }, [branch, branches.data, repositories.data, repository]);

  useEffect(() => {
    setSelectedAddons(preview.data?.addons ?? []);
  }, [preview.data?.addons]);

  const canConfirm = Boolean(
    installationId && repository && branch && preview.data?.is_node_app && !confirm.isPending,
  );

  function reset() {
    setRepository(null);
    setBranch(null);
    setSelectedAddons([]);
    setImportId(null);
    setStage("source");
    confirm.reset();
  }

  function toggle(addon: Addon) {
    setSelectedAddons((current) =>
      current.includes(addon) ? current.filter((item) => item !== addon) : [...current, addon],
    );
  }

  async function startImport() {
    if (!installationId || !repository || !branch) return;
    const created = await confirm.mutateAsync({
      installationId,
      repository,
      branch,
      addons: selectedAddons,
    });
    setImportId(created.import_id);
  }

  return (
    <>
      <button
        className="rounded-md border border-ink-faint/40 bg-surface-raised px-3 py-2 text-caption text-ink hover:border-accent hover:text-accent"
        onClick={() => setOpen(true)}
      >
        Import from GitHub
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-surface/80 p-4 backdrop-blur-sm sm:p-6">
          <section className="w-full min-w-0 max-w-lg rounded-lg border border-hairline bg-surface-raised p-5 shadow-2xl sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-heading">Import from GitHub</p>
                <p className="mt-1 text-caption text-ink-mute">Choose a repository, confirm private add-ons, then watch the real deployment.</p>
              </div>
              <button className="text-ink-faint hover:text-ink" onClick={() => { reset(); setOpen(false); }} aria-label="Close">×</button>
            </div>

            {importId ? (
              <div className="mt-6 rounded-md border border-hairline bg-surface p-4">
                <p className="text-caption text-ink">Provisioning {imported.data?.repository ?? repository}.</p>
                <ul className="mt-3">
                  {imported.data?.steps.map((step) => <Step key={step.service_id} step={step} />)}
                </ul>
                {imported.isError ? <p className="mt-3 text-caption text-status-failed">Could not load import progress.</p> : null}
                {imported.data ? (
                  <button
                    className="mt-4 rounded-md bg-accent px-3 py-2 text-caption font-medium text-surface"
                    onClick={() => router.push(`/projects/${imported.data.project_id}/environments/${imported.data.environment_id}`)}
                  >
                    Open imported project
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="mt-6 space-y-4 rounded-md border border-hairline bg-surface p-4">
                {status.isLoading ? <p className="text-caption text-ink-mute">Checking GitHub App setup…</p> : null}
                {status.isError ? <p className="text-caption text-status-failed">Could not check GitHub App setup.</p> : null}
                {status.data && !status.data.configured ? (
                  <div className="space-y-2 text-caption text-ink-mute">
                    <p>GitHub import is not enabled for this Rudder instance yet.</p>
                    <p>Ask the workspace operator to connect the Rudder GitHub App, then reopen this dialog.</p>
                  </div>
                ) : null}
                {status.data?.configured ? (
                  <>
                    {installations.isLoading ? <p className="text-caption text-ink-mute">Finding your GitHub App connection…</p> : null}
                    {installations.isError ? <p className="text-caption text-status-failed">Could not load GitHub App installations.</p> : null}
                    {installations.data?.length === 0 ? <p className="text-caption text-ink-mute">Redirecting to GitHub to connect your repositories…</p> : null}
                    {(installations.data?.length ?? 0) > 0 ? <label className="block text-caption text-ink-mute">GitHub connection
                      <select value={installationId ?? ""} onChange={(event) => { reset(); setInstallationId(Number(event.target.value) || null); }} className="mt-1 w-full rounded border border-hairline bg-surface-raised px-2 py-2 text-ink">
                        {(installations.data ?? []).map((row) => <option key={row.id} value={row.id}>{row.account_login} · {row.repository_selection === "all" ? "all repositories" : "selected repositories"}</option>)}
                      </select>
                    </label> : null}
                    {installationId ? (
                      <label className="block text-caption text-ink-mute">Repository
                        <select value={repository ?? ""} onChange={(event) => { setRepository(event.target.value || null); setBranch(null); setStage("source"); }} className="mt-1 w-full rounded border border-hairline bg-surface-raised px-2 py-2 text-ink">
                          <option value="">Choose a repository</option>
                          {(repositories.data ?? []).map((row) => <option key={row.full_name} value={row.full_name}>{row.full_name}{row.private ? " · private" : ""}</option>)}
                        </select>
                      </label>
                    ) : null}
                    {repositories.isLoading ? <p className="text-caption text-ink-mute">Loading repositories…</p> : null}
                    {repositories.isError ? <p className="text-caption text-status-failed">Could not load repositories for this installation.</p> : null}
                    {repository ? <label className="block text-caption text-ink-mute">Branch
                      <select value={branch ?? ""} onChange={(event) => { setBranch(event.target.value || null); setStage("source"); }} className="mt-1 w-full rounded border border-hairline bg-surface-raised px-2 py-2 text-ink">
                        {(branches.data ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label> : null}
                    {stage === "source" && installationId && repository && branch ? <button onClick={() => setStage("review")} className="rounded-md bg-accent px-3 py-2 text-caption font-medium text-surface">Continue</button> : null}
                    {stage === "review" && preview.data ? (
                      <div className="rounded border border-hairline p-3 text-caption">
                        {preview.data.is_node_app ? <p className="text-ink">Node.js application detected.</p> : <p className="text-status-failed">This repository is not an Express Node.js application. Phase 1 imports Node apps only.</p>}
                        {preview.data.addons.map((addon) => <label key={addon} className="mt-2 flex items-center gap-2 text-ink"><input type="checkbox" checked={selectedAddons.includes(addon)} onChange={() => toggle(addon)} /> Provision private {addon === "postgres" ? "PostgreSQL 16" : "Redis 7"}</label>)}
                        {preview.data.externally_managed.map((addon) => <p key={addon} className="mt-2 text-ink-mute">{addon} is already externally configured and will not be provisioned.</p>)}
                        <p className="mt-3 text-ink-faint">Only the app gets a public URL. Add-ons get encrypted credentials, private DNS, and persistent volumes.</p>
                      </div>
                    ) : null}
                    {stage === "review" && preview.isLoading ? <p className="text-caption text-ink-mute">Inspecting package.json…</p> : null}
                    {stage === "review" && preview.isError ? <p className="text-caption text-status-failed">Could not inspect this repository.</p> : null}
                    {stage === "review" ? <div className="flex items-center gap-3"><button onClick={() => setStage("source")} className="rounded-md border border-hairline px-3 py-2 text-caption text-ink">Back</button><button disabled={!canConfirm} onClick={() => void startImport()} className="rounded-md bg-accent px-3 py-2 text-caption font-medium text-surface disabled:cursor-not-allowed disabled:opacity-40">{confirm.isPending ? "Creating deployment…" : "Confirm and deploy"}</button></div> : null}
                    {stage === "review" && confirm.isError ? <p className="text-caption text-status-failed">{confirm.error.message}</p> : null}
                  </>
                ) : null}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </>
  );
}
