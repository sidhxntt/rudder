"use client";

import { useParams, useRouter } from "next/navigation";

import {
  useCloneEnvironment,
  useDeleteEnvironment,
  useEnvironments,
  useProjects,
  useServices,
} from "@/lib/queries";
import { useSession } from "@/lib/session";

/**
 * Says where you are, and who you are. No other actions — those live on the
 * thing they act on.
 */
export function TopBar() {
  const params = useParams();
  const session = useSession();
  const router = useRouter();
  const projectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const environmentId =
    typeof params?.environmentId === "string" ? params.environmentId : undefined;

  const projects = useProjects();
  const environments = useEnvironments(projectId);
  const services = useServices(environmentId);
  const clone = useCloneEnvironment(projectId);
  const destroy = useDeleteEnvironment(projectId);

  const project = (projects.data ?? []).find((p) => p.id === projectId);
  const environment = (environments.data ?? []).find((e) => e.id === environmentId);
  const isWorkspace = !projectId;

  async function cloneCurrentEnvironment() {
    if (!environment || !projectId) return;
    const name = window.prompt(`Clone ${environment.name} as:`, `${environment.name}-copy`);
    if (!name?.trim()) return;
    const created = await clone.mutateAsync({ environmentId: environment.id, name: name.trim() });
    router.push(`/projects/${projectId}/environments/${created.id}`);
  }

  async function destroyCurrentEnvironment() {
    if (!environment || !projectId || environment.is_production) return;
    if (!window.confirm(`Destroy environment “${environment.name}”? This deletes its services and volumes.`)) {
      return;
    }
    await destroy.mutateAsync(environment.id);
    router.push(`/projects/${projectId}`);
  }

  return (
    <header className="flex h-11 shrink-0 items-center gap-sm border-b border-hairline bg-surface-soft px-sm sm:gap-md sm:px-lg">
      <div className="flex min-w-0 flex-1 items-center gap-sm">
        {isWorkspace ? (
          <span className="truncate text-caption font-medium text-ink">Workspace</span>
        ) : (
          <>
            <span className="truncate text-caption text-ink-mute">{project?.name ?? "—"}</span>
            <span className="text-ink-faint" aria-hidden>
              /
            </span>
            <span className="truncate text-caption font-medium text-ink">
              {environment?.name ?? "—"}
            </span>
          </>
        )}
        {environment?.is_production ? (
          <span className="rounded-xs border border-hairline-strong px-xs py-xxs text-micro uppercase tracking-wide text-ink-mute">
            production
          </span>
        ) : null}
        {environment ? (
          <span className="ml-sm flex gap-xs">
            <button
              type="button"
              onClick={() => void cloneCurrentEnvironment()}
              disabled={clone.isPending}
              className="rounded-sm border border-hairline px-xs py-xxs text-micro text-ink-mute hover:text-ink disabled:opacity-50"
            >
              clone
            </button>
            {!environment.is_production ? (
              <button
                type="button"
                onClick={() => void destroyCurrentEnvironment()}
                disabled={destroy.isPending}
                className="rounded-sm border border-hairline px-xs py-xxs text-micro text-status-failed hover:border-status-failed disabled:opacity-50"
              >
                destroy
              </button>
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
        {session.state.status === "authenticated" ? (
          <span className="flex items-center gap-sm">
            <span className="hidden max-w-40 truncate text-ink-faint sm:inline">
              {session.state.user.email}
            </span>
            <button
              type="button"
              onClick={() => void session.signOut()}
              className="rounded-sm px-xs py-xxs text-micro text-ink-mute hover:text-ink"
            >
              sign out
            </button>
          </span>
        ) : null}
      </div>
    </header>
  );
}
