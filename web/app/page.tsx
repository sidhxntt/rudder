"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { useProjects } from "@/lib/queries";

import { GitHubImportDialog } from "./projects/[projectId]/environments/[environmentId]/github-import-dialog";

function GitHubMark() {
  return (
    <svg aria-hidden="true" className="h-5 w-5 shrink-0" fill="currentColor" viewBox="0 0 24 24">
      <path
        clipRule="evenodd"
        fillRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.009-.868-.014-1.703-2.782.605-3.369-1.342-3.369-1.342-.455-1.157-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.071 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.091-.647.349-1.088.635-1.339-2.221-.253-4.556-1.113-4.556-4.951 0-1.093.39-1.987 1.03-2.687-.103-.253-.447-1.271.098-2.65 0 0 .84-.27 2.75 1.027A9.564 9.564 0 0 1 12 6.336a9.59 9.59 0 0 1 2.504.337c1.909-1.297 2.748-1.027 2.748-1.027.546 1.379.202 2.397.1 2.65.64.7 1.028 1.594 1.028 2.687 0 3.848-2.339 4.695-4.568 4.943.359.31.678.921.678 1.856 0 1.339-.012 2.419-.012 2.747 0 .269.18.58.688.481A10.02 10.02 0 0 0 22 12.017C22 6.484 17.523 2 12 2Z"
      />
    </svg>
  );
}

function ArrowUpRight() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16">
      <path d="M4 12 12 4M6 4h6v6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

/** The workspace landing page: active projects plus a real first-deploy path. */
export default function IndexPage() {
  const router = useRouter();
  const search = useSearchParams();
  const projects = useProjects();

  useEffect(() => {
    const installationId = search.get("installation_id");
    const returnPath = window.sessionStorage.getItem("rudder:github-import-return");
    if (installationId && returnPath) {
      const destination = new URL(returnPath, window.location.origin);
      destination.searchParams.set("installation_id", installationId);
      window.sessionStorage.removeItem("rudder:github-import-return");
      router.replace(`${destination.pathname}?${destination.searchParams.toString()}`);
    }
  }, [router, search]);

  return (
    <div className="rd-scroll h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-xl py-xxl sm:px-xxl sm:py-huge">
        <header className="max-w-2xl">
          <div className="flex items-center gap-sm text-caption text-accent">
            <span className="h-2 w-2 rounded-full bg-accent" aria-hidden />
            Workspace
          </div>
          <h1 className="mt-md text-display-lg text-ink">Deploy from the repository you already trust.</h1>
          <p className="mt-md max-w-xl text-body text-ink-secondary">
            Connect a GitHub repository, inspect the resolved Compose release, and let Rudder run the application and its private dependencies locally.
          </p>
        </header>

        <section className="mt-xxl overflow-hidden rounded-lg border border-hairline bg-surface-raised shadow-elev-1">
          <div className="flex flex-col gap-xl px-xl py-xl sm:flex-row sm:items-end sm:justify-between sm:px-xxl sm:py-xxl">
            <div className="max-w-lg">
              <div className="flex h-10 w-10 items-center justify-center rounded-md border border-hairline bg-surface text-ink">
                <GitHubMark />
              </div>
              <h2 className="mt-lg text-heading-lg text-ink">Start with a GitHub repository</h2>
              <p className="mt-xs text-caption text-ink-mute">
                Rudder reads the branch you choose. A repository <span className="font-mono text-ink-secondary">compose.yaml</span> is used directly; otherwise Rudder prepares a safe app release for you to review.
              </p>
            </div>
            <GitHubImportDialog
              triggerLabel="Import from GitHub"
              triggerClassName="inline-flex shrink-0 items-center justify-center gap-sm rounded-sm bg-accent px-lg py-md text-button font-medium text-on-accent transition-colors hover:bg-accent-deep"
            />
          </div>

          <div className="grid border-t border-hairline sm:grid-cols-3">
            <div className="px-xl py-lg sm:border-r sm:border-hairline">
              <p className="text-micro text-ink-faint">01 · Choose source</p>
              <p className="mt-xs text-caption text-ink">Repository and branch</p>
            </div>
            <div className="px-xl py-lg sm:border-r sm:border-hairline">
              <p className="text-micro text-ink-faint">02 · Review release</p>
              <p className="mt-xs text-caption text-ink">Services and private add-ons</p>
            </div>
            <div className="px-xl py-lg">
              <p className="text-micro text-ink-faint">03 · Go live</p>
              <p className="mt-xs text-caption text-ink">Build logs and public URL</p>
            </div>
          </div>
        </section>

        <section className="mt-huge">
          <div className="flex items-end justify-between gap-lg border-b border-hairline pb-md">
            <div>
              <h2 className="text-heading-lg text-ink">Projects</h2>
              <p className="mt-xxs text-caption text-ink-mute">Your recent deployment workspaces.</p>
            </div>
            {projects.data?.length ? <span className="text-micro text-ink-faint">{projects.data.length} total</span> : null}
          </div>

          {projects.isPending ? (
            <div className="py-xxl text-caption text-ink-mute">Loading your workspace…</div>
          ) : null}

          {projects.isError ? (
            <div className="flex flex-col gap-md py-xxl sm:flex-row sm:items-center sm:justify-between">
              <p className="text-caption text-status-failed">Could not load projects. Check the control plane, then try again.</p>
              <button
                type="button"
                onClick={() => void projects.refetch()}
                className="w-fit rounded-sm border border-hairline-strong px-md py-sm text-caption text-ink hover:border-accent hover:text-accent"
              >
                Try again
              </button>
            </div>
          ) : null}

          {projects.isSuccess && projects.data.length === 0 ? (
            <div className="py-xxl">
              <p className="text-caption text-ink-secondary">No projects yet.</p>
              <p className="mt-xs max-w-lg text-caption text-ink-mute">
                Your first import creates a project, a production environment, and the services declared by its Compose release.
              </p>
            </div>
          ) : null}

          {projects.isSuccess && projects.data.length > 0 ? (
            <ul className="divide-y divide-hairline">
              {projects.data.map((project) => (
                <li key={project.id}>
                  <Link
                    href={`/projects/${project.id}`}
                    className="flex items-center justify-between gap-lg py-lg text-caption text-ink transition-colors hover:text-accent"
                  >
                    <span>{project.name}</span>
                    <ArrowUpRight />
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
    </div>
  );
}
