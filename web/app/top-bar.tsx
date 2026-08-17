"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useDeleteEnvironment,
  useCloneEnvironment,
  useEnvironments,
  useProjects,
  useServices,
  useUpdateProject,
} from "@/lib/queries";

function ArrowLeftIcon() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16">
      <path d="M13 8H3m4-4-4 4 4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

/** A persistent, compact return path that never turns the Rudder mark into navigation. */
export function BackToWorkspaceButton() {
  return (
    <Link
      href="/dashboard"
      aria-label="Back to workspace"
      title="Back to workspace"
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-xs text-ink-mute outline-none transition-colors hover:bg-surface-raised hover:text-ink focus-visible:bg-surface-raised focus-visible:text-accent"
    >
      <ArrowLeftIcon />
    </Link>
  );
}

/**
 * Says where you are, and who you are. No other actions — those live on the
 * thing they act on.
 */
export function TopBar() {
  const params = useParams();
  const router = useRouter();
  const [isLocal, setIsLocal] = useState(false);
  const [editingProject, setEditingProject] = useState(false);
  const [projectName, setProjectName] = useState("");
  const projectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const environmentId =
    typeof params?.environmentId === "string" ? params.environmentId : undefined;

  const projects = useProjects();
  const environments = useEnvironments(projectId);
  const services = useServices(environmentId);
  const destroy = useDeleteEnvironment(projectId);
  const clone = useCloneEnvironment(projectId);
  const updateProject = useUpdateProject();

  useEffect(() => {
    setIsLocal(window.location.hostname === "localhost");
  }, []);

  const project = (projects.data ?? []).find((p) => p.id === projectId);
  const environment = (environments.data ?? []).find((e) => e.id === environmentId);
  const isWorkspace = !projectId;

  useEffect(() => {
    if (!editingProject) setProjectName(project?.name ?? "");
  }, [editingProject, project?.name]);

  async function destroyCurrentEnvironment() {
    if (!environment || !projectId || environment.is_production) return;
    if (!window.confirm(`Destroy environment “${environment.name}”? This deletes its services and volumes.`)) {
      return;
    }
    await destroy.mutateAsync(environment.id);
    router.push(`/projects/${projectId}`);
  }

  async function cloneCurrentEnvironment() {
    if (!environment || !projectId) return;
    const sourceName = isLocal && environment.is_production ? "development" : environment.name;
    const name = window.prompt(
      `Clone ${sourceName} for production as:`,
      `${sourceName}-production`,
    );
    if (!name?.trim()) return;
    const created = await clone.mutateAsync({ environmentId: environment.id, name: name.trim() });
    router.push(`/projects/${projectId}/environments/${created.id}`);
  }

  async function saveProjectName() {
    if (!projectId || !projectName.trim() || projectName.trim() === project?.name) {
      setEditingProject(false);
      return;
    }
    await updateProject.mutateAsync({ projectId, name: projectName.trim() });
    setEditingProject(false);
  }

  const environmentLabel =
    isLocal && environment?.is_production ? "development" : (environment?.name ?? "—");
  const deploymentLabel = isLocal ? "development" : "production";

  return (
    <header className="flex h-11 shrink-0 items-center gap-sm border-b border-hairline bg-surface-soft px-sm sm:gap-md sm:px-lg">
      <div className="flex min-w-0 flex-1 items-center gap-sm">
        {isWorkspace ? (
          <span className="truncate text-caption font-medium text-ink">Workspace</span>
        ) : (
          <>
            <BackToWorkspaceButton />
            {editingProject ? (
              <Input
                autoFocus
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                onBlur={() => void saveProjectName()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveProjectName();
                  if (event.key === "Escape") setEditingProject(false);
                }}
                aria-label="Project name"
                className="h-7 max-w-64 font-sans"
              />
            ) : (
              <button
                type="button"
                onDoubleClick={() => setEditingProject(true)}
                title="Double-click to rename project"
                className="truncate text-caption text-ink-mute outline-none transition-colors hover:text-ink focus-visible:text-accent"
              >
                {project?.name ?? "—"}
              </button>
            )}
            <span className="text-ink-faint" aria-hidden>
              /
            </span>
            <span className="truncate text-caption font-medium text-ink">
              {environmentLabel}
            </span>
          </>
        )}
        {environment?.is_production ? (
          <span className="rounded-xs border border-hairline-strong px-xs py-xxs text-micro uppercase tracking-wide text-ink-mute">
            {deploymentLabel}
          </span>
        ) : null}
        {environment ? (
          <span className="ml-sm flex gap-xs">
            <Button
              onClick={() => void cloneCurrentEnvironment()}
              disabled={clone.isPending}
              variant="outline"
              size="sm"
            >
              Clone to production
            </Button>
            {!environment.is_production ? (
              <Button
                onClick={() => void destroyCurrentEnvironment()}
                disabled={destroy.isPending}
                variant="destructive"
                size="sm"
              >
                destroy
              </Button>
            ) : null}
          </span>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-sm text-micro text-ink-mute sm:gap-lg">
        {environment?.wg_subnet ? (
          <span className="font-mono">{environment.wg_subnet}</span>
        ) : null}
        <span>
          {services.data ? `${services.data.length} services` : environment ? "…" : ""}
        </span>
      </div>
    </header>
  );
}
