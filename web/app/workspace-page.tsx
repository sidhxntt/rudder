"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { useNodes, useProjects } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { shortAgo } from "@/lib/status";

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

function SignalDot({ healthy }: { healthy: boolean }) {
  return <span aria-hidden="true" className={`h-2 w-2 rounded-full ${healthy ? "bg-status-success" : "bg-status-failed"}`} />;
}

/** The signed-in landing surface: current work, runtime signal, and the next deploy. */
export default function WorkspacePage() {
  const router = useRouter();
  const search = useSearchParams();
  const session = useSession();
  const projects = useProjects();
  const nodes = useNodes();
  const projectList = [...(projects.data ?? [])].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );
  const nodeList = nodes.data ?? [];
  const healthyNodeCount = nodeList.filter((node) => node.status === "healthy").length;
  const userName = session.state.status === "authenticated"
    ? session.state.user.github_login ?? session.state.user.email.split("@")[0]
    : "there";
  const recentEvents = [
    ...projectList.map((project) => ({
      id: `project-${project.id}`,
      at: project.created_at,
      label: "Project created",
      detail: project.name,
      healthy: true,
    })),
    ...nodeList
      .filter((node) => node.last_heartbeat_at)
      .map((node) => ({
        id: `node-${node.id}`,
        at: node.last_heartbeat_at as string,
        label: node.status === "healthy" ? "Node reported healthy" : "Node status reported",
        detail: node.hostname,
        healthy: node.status === "healthy",
      })),
  ].sort((left, right) => Date.parse(right.at) - Date.parse(left.at)).slice(0, 6);
  const isReturning = projectList.length > 0;

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
    <main aria-labelledby="workspace-title" className="rd-scroll h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-xl py-xxl sm:px-xxl sm:py-xxl lg:py-huge">
        <header className="grid gap-xxl border-b border-hairline pb-xxl lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-7">
            <p className="font-mono text-micro uppercase tracking-widest text-accent">Rudder workspace</p>
            <h1 id="workspace-title" className="mt-md max-w-2xl text-display-lg text-ink">
              {isReturning ? `Good to have you back, ${userName}.` : "Your deployment control plane starts here."}
            </h1>
            <p className="mt-lg max-w-2xl text-body text-ink-secondary">
              {isReturning
                ? "Continue from a project, inspect the runtime fleet, or bring in another repository."
                : "Bring in a GitHub repository to review its release, services, and private dependencies before deployment."}
            </p>
          </div>

          <section aria-labelledby="workspace-overview-title" className="border-t border-hairline pt-lg lg:col-span-5 lg:border-l lg:border-t-0 lg:pl-xxl lg:pt-0">
            <h2 id="workspace-overview-title" className="text-heading-md text-ink">Workspace overview</h2>
            <dl className="mt-lg grid grid-cols-2 gap-x-xl border-t border-hairline pt-lg">
              <div>
                <dt className="font-mono text-micro uppercase tracking-wide text-ink-faint">Projects</dt>
                <dd className="mt-xs text-heading-lg text-ink">
                  {projects.isPending ? "—" : `${projectList.length} project${projectList.length === 1 ? "" : "s"}`}
                </dd>
              </div>
              <div>
                <dt className="font-mono text-micro uppercase tracking-wide text-ink-faint">Runtime fleet</dt>
                <dd className="mt-xs flex items-center gap-sm text-heading-lg text-ink">
                  {nodes.isPending ? "—" : <><SignalDot healthy={healthyNodeCount > 0} />{`${healthyNodeCount} healthy node${healthyNodeCount === 1 ? "" : "s"}`}</>}
                </dd>
              </div>
            </dl>
          </section>
        </header>

        <section aria-labelledby="import-title" className="mt-xxl border-y border-hairline bg-surface-raised">
          <div className="grid gap-xl px-xl py-xl sm:px-xxl sm:py-xxl lg:grid-cols-12 lg:items-center">
            <div className="flex gap-lg lg:col-span-8">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface text-ink ring-1 ring-inset ring-hairline">
                <GitHubMark />
              </div>
              <div>
                <h2 id="import-title" className="text-heading-lg text-ink">Bring in a repository</h2>
                <p className="mt-xs max-w-2xl text-caption text-ink-mute">
                  Choose a branch, inspect its release, then deploy the application and any private Compose dependencies from one place.
                </p>
              </div>
            </div>
            <div className="lg:col-span-4 lg:justify-self-end">
              <GitHubImportDialog
                triggerLabel="Import from GitHub"
                triggerClassName="inline-flex min-h-11 items-center justify-center gap-sm rounded-sm bg-accent px-lg py-md text-button font-medium text-on-accent transition-colors hover:bg-accent-deep"
              />
            </div>
          </div>
          <div className="grid border-t border-hairline sm:grid-cols-3">
            {["Choose source", "Review release", "Deploy with evidence"].map((step, index) => (
              <div key={step} className="flex items-baseline gap-sm px-xl py-md sm:border-r sm:border-hairline last:sm:border-r-0">
                <span className="font-mono text-micro text-accent">0{index + 1}</span>
                <p className="text-caption text-ink-secondary">{step}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="mt-xxl grid gap-xxl lg:grid-cols-12 lg:gap-0">
          <section aria-labelledby="projects-title" className="lg:col-span-8 lg:pr-xxl">
            <div className="flex items-end justify-between gap-lg border-b border-hairline pb-md">
              <div>
                <h2 id="projects-title" className="text-heading-lg text-ink">Project inventory</h2>
                <p className="mt-xxs text-caption text-ink-mute">Open a project to inspect its environments and service topology.</p>
              </div>
              {projects.isSuccess ? <span className="font-mono text-micro text-ink-faint">{projectList.length} total</span> : null}
            </div>

            {projects.isPending ? <p className="py-xxl text-caption text-ink-mute">Loading your project inventory…</p> : null}
            {projects.isError ? (
              <div className="flex flex-col gap-md py-xxl sm:flex-row sm:items-center sm:justify-between">
                <p className="text-caption text-status-failed">Could not load projects. Check the control plane, then try again.</p>
                <button type="button" onClick={() => void projects.refetch()} className="w-fit rounded-sm border border-hairline-strong px-md py-sm text-caption text-ink hover:border-accent hover:text-accent">Try again</button>
              </div>
            ) : null}
            {projects.isSuccess && projectList.length === 0 ? (
              <div className="py-xxl">
                <p className="text-heading-md text-ink">No projects yet.</p>
                <p className="mt-xs max-w-lg text-caption text-ink-mute">Your first import creates a project, a production environment, and the services declared by its Compose release.</p>
              </div>
            ) : null}
            {projects.isSuccess && projectList.length > 0 ? (
              <ul className="divide-y divide-hairline">
                {projectList.map((project, index) => (
                  <li key={project.id}>
                    <Link href={`/projects/${project.id}`} aria-label={`Open ${project.name} project`} className="group grid grid-cols-[auto_1fr_auto] items-center gap-lg py-lg text-ink transition-colors hover:text-accent">
                      <span className="font-mono text-micro text-ink-faint">{String(index + 1).padStart(2, "0")}</span>
                      <span className="min-w-0">
                        <span className="block truncate text-button">{project.name}</span>
                        <span className="mt-xxs block text-micro text-ink-faint">Created {shortAgo(project.created_at)}</span>
                      </span>
                      <ArrowUpRight />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <section aria-labelledby="activity-title" className="border-t border-hairline pt-xl lg:col-span-4 lg:border-l lg:border-t-0 lg:pl-xxl lg:pt-0">
            <div className="flex items-end justify-between gap-lg border-b border-hairline pb-md">
              <div>
                <h2 id="activity-title" className="text-heading-lg text-ink">Recent activity</h2>
                <p className="mt-xxs text-caption text-ink-mute">Recorded by this workspace.</p>
              </div>
              {recentEvents.length ? <span className="font-mono text-micro text-ink-faint">{recentEvents.length} latest</span> : null}
            </div>
            {recentEvents.length ? (
              <ul className="divide-y divide-hairline">
                {recentEvents.map((event) => (
                  <li key={event.id} className="flex gap-sm py-md">
                    <span className="mt-xs"><SignalDot healthy={event.healthy} /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-caption text-ink"><span className="text-ink-mute">{event.label}</span>{" · "}{event.detail}</p>
                      <time dateTime={event.at} className="mt-xxs block font-mono text-micro text-ink-faint">{shortAgo(event.at)}</time>
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="py-xl text-caption text-ink-mute">No recorded activity yet. Import a repository to create your first project.</p>}
          </section>
        </div>

        <section aria-labelledby="fleet-title" className="mt-xxl border-t border-hairline pt-xl">
          <div className="flex items-end justify-between gap-lg border-b border-hairline pb-md">
            <div>
              <h2 id="fleet-title" className="text-heading-lg text-ink">Fleet</h2>
              <p className="mt-xxs text-caption text-ink-mute">Hosts registered to run your applications.</p>
            </div>
            {nodes.isSuccess ? <span className="font-mono text-micro text-ink-faint">{nodeList.length} total</span> : null}
          </div>
          {nodes.isPending ? <p className="py-xxl text-caption text-ink-mute">Loading runtime fleet…</p> : null}
          {nodes.isError ? (
            <div className="flex flex-col gap-md py-xxl sm:flex-row sm:items-center sm:justify-between">
              <p className="text-caption text-status-failed">Could not load nodes. Check the control plane, then try again.</p>
              <button type="button" onClick={() => void nodes.refetch()} className="w-fit rounded-sm border border-hairline-strong px-md py-sm text-caption text-ink hover:border-accent hover:text-accent">Try again</button>
            </div>
          ) : null}
          {nodes.isSuccess && nodeList.length === 0 ? <p className="py-xxl text-caption text-ink-mute">No nodes yet. Once an agent registers, it will appear here.</p> : null}
          {nodes.isSuccess && nodeList.length > 0 ? (
            <ul className="divide-y divide-hairline">
              {nodeList.map((node) => {
                const healthyInstances = node.instances.filter((instance) => instance.status === "healthy").length;
                return (
                  <li key={node.id} className="grid gap-sm py-lg sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] sm:items-center sm:gap-lg">
                    <div className="min-w-0">
                      <p className="truncate text-button text-ink">{node.hostname}</p>
                      <p className="mt-xxs font-mono text-micro text-ink-faint">{node.ip_address}</p>
                    </div>
                    <p className="text-caption text-ink-mute">
                      {node.last_heartbeat_at ? `Last heartbeat ${shortAgo(node.last_heartbeat_at)}` : "Awaiting first heartbeat"}
                    </p>
                    <div className="flex items-center gap-md sm:justify-end">
                      <span className={`inline-flex items-center gap-xs font-mono text-micro ${node.status === "healthy" ? "text-status-success" : "text-status-failed"}`}>
                        <SignalDot healthy={node.status === "healthy"} />{node.status}
                      </span>
                      <span className="font-mono text-micro text-ink-faint">{healthyInstances}/{node.instances.length} instances</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </section>
      </div>
    </main>
  );
}
