"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { useEnvironments, useProjects } from "@/lib/queries";

/**
 * Project / environment selection. Colocated with the root route because the
 * shell wraps every route.
 */
export function Sidebar() {
  const params = useParams();
  const activeProjectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const activeEnvironmentId =
    typeof params?.environmentId === "string" ? params.environmentId : undefined;

  const projects = useProjects();
  const environments = useEnvironments(activeProjectId);

  return (
    <nav className="rd-scroll flex w-56 shrink-0 flex-col overflow-y-auto border-r border-hairline bg-surface-soft">
      <div className="flex h-11 shrink-0 items-center gap-sm border-b border-hairline px-md">
        <span className="h-2 w-2 rounded-full bg-accent" aria-hidden />
        <span className="text-caption font-medium tracking-tight text-ink">rudder</span>
      </div>

      <div className="px-md pt-lg">
        <p className="text-micro uppercase tracking-wider text-ink-faint">Projects</p>
      </div>

      {projects.isPending ? (
        <p className="px-md pt-sm text-micro text-ink-faint">loading…</p>
      ) : null}

      {projects.isError ? (
        <p className="px-md pt-sm text-micro text-status-failed">
          could not reach the control plane
        </p>
      ) : null}

      <ul className="px-sm pb-lg pt-xs">
        {(projects.data ?? []).map((project) => {
          const isActive = project.id === activeProjectId;
          return (
            <li key={project.id} className="pt-xxs">
              <Link
                href={`/projects/${project.id}`}
                className={[
                  "block rounded-xs px-sm py-xs text-caption",
                  isActive ? "bg-surface-raised text-ink" : "text-ink-secondary hover:text-ink",
                ].join(" ")}
              >
                {project.name}
              </Link>

              {isActive ? (
                <ul className="border-l border-hairline pl-sm ml-sm mt-xxs">
                  {(environments.data ?? []).map((environment) => {
                    const isCurrent = environment.id === activeEnvironmentId;
                    return (
                      <li key={environment.id}>
                        <Link
                          href={`/projects/${project.id}/environments/${environment.id}`}
                          className={[
                            "flex items-center justify-between rounded-xs px-sm py-xs text-micro",
                            isCurrent
                              ? "bg-surface-raised text-ink"
                              : "text-ink-mute hover:text-ink-secondary",
                          ].join(" ")}
                        >
                          <span>{environment.name}</span>
                          {environment.is_production ? (
                            <span
                              className="h-1.5 w-1.5 rounded-full bg-accent"
                              aria-label="production"
                            />
                          ) : null}
                        </Link>
                      </li>
                    );
                  })}
                  {environments.isPending ? (
                    <li className="px-sm py-xs text-micro text-ink-faint">loading…</li>
                  ) : null}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>

      <div className="mt-auto border-t border-hairline px-md py-sm">
        <p className="text-micro text-ink-faint">
          Phase 1 · single host · build logs only
        </p>
      </div>
    </nav>
  );
}
