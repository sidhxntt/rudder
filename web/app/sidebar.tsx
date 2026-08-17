"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useEnvironments, useProjects } from "@/lib/queries";
import { useSession } from "@/lib/session";

/**
 * Project / environment selection. Colocated with the root route because the
 * shell wraps every route.
 */
export function Sidebar() {
  const params = useParams();
  const activeProjectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const activeEnvironmentId =
    typeof params?.environmentId === "string" ? params.environmentId : undefined;
  const [isLocal, setIsLocal] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const session = useSession();

  const projects = useProjects();
  const environments = useEnvironments(activeProjectId);
  const projectList = [...(projects.data ?? [])].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );

  useEffect(() => {
    setIsLocal(window.location.hostname === "localhost");
  }, []);

  return (
    <nav className="flex w-56 shrink-0 flex-col overflow-hidden border-r border-hairline bg-surface-soft">
      <div className="flex h-11 shrink-0 items-center gap-sm border-b border-hairline px-md">
        <span className="h-2 w-2 rounded-full bg-accent" aria-hidden />
        <span className="text-caption font-medium tracking-tight text-ink">rudder</span>
      </div>

      <div className="rd-scroll min-h-0 flex-1 overflow-y-auto">
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
        {projectList.map((project) => {
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
                          <span>
                            {isLocal && environment.is_production ? "development" : environment.name}
                          </span>
                          {environment.is_production ? (
                            <span
                              className="h-1.5 w-1.5 rounded-full bg-accent"
                              aria-label={isLocal ? "development" : "production"}
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
      </div>

      {session.state.status === "authenticated" ? (
        <div className="relative shrink-0 border-t border-hairline p-sm">
          <button
            type="button"
            onClick={() => setAccountMenuOpen((open) => !open)}
            aria-expanded={accountMenuOpen}
            aria-haspopup="menu"
            aria-label="Open account menu"
            className="flex w-full items-center gap-sm rounded-sm px-xs py-xs text-left transition-colors hover:bg-surface-raised"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full border border-hairline-strong bg-surface-raised text-micro font-medium text-ink">
              {(session.state.user.github_avatar_url ??
                (session.state.user.github_login ? `https://github.com/${session.state.user.github_login}.png?size=96` : null)) && !avatarFailed ? (
                <img
                  src={session.state.user.github_avatar_url ?? `https://github.com/${session.state.user.github_login}.png?size=96`}
                  alt=""
                  referrerPolicy="no-referrer"
                  className="h-full w-full object-cover"
                  onError={() => setAvatarFailed(true)}
                />
              ) : (
                (session.state.user.github_login ?? session.state.user.email).slice(0, 1).toUpperCase()
              )}
            </span>
            <span className="min-w-0 truncate text-micro text-ink-secondary">
              {session.state.user.github_login ?? session.state.user.email}
            </span>
          </button>
          {accountMenuOpen ? (
            <div role="menu" className="absolute bottom-12 left-sm z-30 w-52 overflow-hidden rounded-md border border-hairline-strong bg-surface-raised shadow-elev-2">
              <p className="truncate border-b border-hairline px-md py-sm text-micro text-ink-secondary">
                {session.state.user.github_login ? `@${session.state.user.github_login}` : "GitHub account"}
              </p>
              {session.state.user.github_login ? (
                <a
                  role="menuitem"
                  href={`https://github.com/${session.state.user.github_login}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex w-full items-center px-md py-sm text-micro text-ink-mute transition-colors hover:bg-surface-soft hover:text-ink"
                >
                  View GitHub profile
                </a>
              ) : null}
              <Button role="menuitem" onClick={() => void session.signOut()} variant="ghost" className="w-full justify-start rounded-none px-md py-sm text-left">
                Sign out
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

    </nav>
  );
}
