"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDeleteProject, useProjects, useUpdateProject } from "@/lib/queries";

/** Project-wide controls live here rather than being confused with service settings. */
export function ProjectSettings() {
  const params = useParams();
  const router = useRouter();
  const projectId = typeof params?.projectId === "string" ? params.projectId : undefined;
  const projects = useProjects();
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();
  const project = (projects.data ?? []).find((item) => item.id === projectId);
  const [name, setName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => setName(project?.name ?? ""), [project?.name]);

  async function saveName() {
    if (!projectId || !name.trim() || name.trim() === project?.name) return;
    await updateProject.mutateAsync({ projectId, name: name.trim() });
  }

  async function copyProjectId() {
    if (!projectId || !navigator.clipboard) return;
    await navigator.clipboard.writeText(projectId);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }

  async function removeProject() {
    if (!projectId || !project || confirmation !== project.name) return;
    if (!window.confirm(`Delete project “${project.name}” and all of its environments, services, deployments, and volumes?`)) return;
    await deleteProject.mutateAsync(projectId);
    router.replace("/");
  }

  if (!project) {
    return <p className="px-lg py-md text-micro text-ink-faint">loading project settings…</p>;
  }

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto">
      <section className="border-b border-hairline px-lg py-lg">
        <h3 className="text-caption font-medium text-ink">General</h3>
        <p className="pt-xxs text-micro text-ink-mute">Project-wide identity and deployment defaults.</p>

        <label className="mt-lg block">
          <span className="text-micro text-ink-secondary">Project name</span>
          <div className="mt-xs flex gap-sm">
            <Input value={name} onChange={(event) => setName(event.target.value)} aria-label="Project name" />
            <Button size="sm" onClick={() => void saveName()} disabled={updateProject.isPending || !name.trim() || name.trim() === project.name}>
              {updateProject.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </label>

        <dl className="mt-lg divide-y divide-hairline border-y border-hairline">
          <div className="flex items-start justify-between gap-lg py-sm">
            <div>
              <dt className="text-micro text-ink-secondary">Default environment</dt>
              <dd className="pt-xxs text-micro text-ink-mute">Every project starts with a production environment.</dd>
            </div>
            <span className="shrink-0 rounded-xs border border-hairline-strong px-xs py-xxs text-micro uppercase tracking-wide text-ink-mute">production</span>
          </div>
          <div className="flex items-center justify-between gap-lg py-sm">
            <div className="min-w-0">
              <dt className="text-micro text-ink-secondary">Project ID</dt>
              <dd className="truncate pt-xxs font-mono text-micro text-ink-faint">{project.id}</dd>
            </div>
            <Button size="sm" variant="ghost" onClick={() => void copyProjectId()}>{copied ? "Copied" : "Copy"}</Button>
          </div>
        </dl>
      </section>

      <section className="px-lg py-lg">
        <h3 className="text-caption font-medium text-status-failed">Danger zone</h3>
        <p className="pt-xxs text-micro text-ink-mute">Deleting a project permanently removes its environments, services, deployments, domains, variables, and volumes.</p>
        <label className="mt-lg block">
          <span className="text-micro text-ink-secondary">Type <span className="font-mono text-ink">{project.name}</span> to confirm</span>
          <Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-xs" aria-label="Confirm project deletion" />
        </label>
        <Button
          variant="destructive"
          size="sm"
          className="mt-md"
          onClick={() => void removeProject()}
          disabled={deleteProject.isPending || confirmation !== project.name}
        >
          {deleteProject.isPending ? "Deleting project…" : "Delete project"}
        </Button>
      </section>
    </div>
  );
}
