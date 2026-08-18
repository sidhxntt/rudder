import * as clack from "@clack/prompts";

type Api = { request(method: string, path: string, body?: unknown): Promise<unknown> };
type PromptApi = Pick<typeof clack, "select" | "multiselect" | "confirm" | "isCancel" | "note">;

export type ImportContext = { projectId: string; environmentId: string };
export type GitHubImportWizardDependencies = { api: Api; prompts?: PromptApi };

type Installation = { id: number; account_login: string; repository_selection: string };
type Repository = { full_name: string; default_branch: string; private: boolean };
type Template = { id: string; name: string; description: string };
type Preview = {
  compose_source: "repository" | "generated";
  addons: string[];
  services: Array<{ name: string; role: string; is_public: boolean }>;
};
type CreatedImport = { import_id: string; project_id: string; environment_id: string };
type ImportProgress = { steps: Array<{ service_name: string | null; status: string; error_message: string | null }> };

/** Create a project through the same reviewed GitHub-import API sequence as the web. */
export async function runGitHubImportWizard({ api, prompts = clack }: GitHubImportWizardDependencies): Promise<ImportContext | undefined> {
  const status = asRecord(await api.request("GET", "/github/import/status"));
  if (status.configured !== true) throw new Error(typeof status.message === "string" ? status.message : "GitHub import is not enabled here.");

  const templates = asArray<Template>(await api.request("GET", "/github/import/templates"));
  const source = await prompts.select<"repository" | string>({
    message: "Choose a source",
    options: [
      { value: "repository", label: "Repository Compose", hint: "Use compose.yaml from your branch" },
      ...templates.map(template => ({ value: template.id, label: template.name, hint: template.description })),
    ],
  });
  if (prompts.isCancel(source)) return;
  const templateId = source === "repository" ? null : source;

  const installations = asArray<Installation>(await api.request("GET", "/github/import/installations"));
  if (!installations.length) throw new Error("No GitHub App installation is connected. Install the Rudder GitHub App, then run `rudder` again.");
  const installationId = await prompts.select<number>({
    message: "Choose GitHub connection",
    options: installations.map(installation => ({
      value: installation.id,
      label: installation.account_login,
      hint: installation.repository_selection === "all" ? "all repositories" : "selected repositories",
    })),
  });
  if (prompts.isCancel(installationId)) return;

  const repositories = asArray<Repository>(await api.request("GET", `/github/import/repositories?installation_id=${installationId}`));
  if (!repositories.length) throw new Error("This GitHub connection has no repositories available to Rudder.");
  const repository = await prompts.select<string>({
    message: "Choose repository",
    options: repositories.map(item => ({ value: item.full_name, label: item.full_name, hint: item.private ? "private" : "public" })),
  });
  if (prompts.isCancel(repository)) return;

  const selectedRepository = repositories.find(item => item.full_name === repository);
  const branches = asArray<string>(await api.request("GET", `/github/import/branches?installation_id=${installationId}&repository=${encodeURIComponent(repository)}`));
  if (!branches.length) throw new Error("Rudder could not find a branch for this repository.");
  const branch = await prompts.select<string>({
    message: "Choose branch",
    options: branches.map(item => ({ value: item, label: item })),
    initialValue: selectedRepository?.default_branch && branches.includes(selectedRepository.default_branch) ? selectedRepository.default_branch : branches[0],
  });
  if (prompts.isCancel(branch)) return;

  const selection = { installation_id: installationId, repository, branch, template_id: templateId };
  const preview = asPreview(await api.request("POST", "/github/import/preview", selection));
  prompts.note(previewSummary(preview), "Review detected release");

  const addons = preview.compose_source === "generated" && preview.addons.length
    ? await prompts.multiselect<string>({
      message: "Select private add-ons",
      options: preview.addons.map(addon => ({ value: addon, label: addon })),
      initialValues: preview.addons,
    })
    : [];
  if (prompts.isCancel(addons)) return;

  const publicServices = preview.services.filter(service => service.role === "web" && service.is_public).map(service => service.name);
  if (!publicServices.length) throw new Error("The reviewed release has no public web service to deploy.");
  const selectedPublicServices = await prompts.multiselect<string>({
    message: "Expose public services",
    options: publicServices.map(name => ({ value: name, label: name })),
    initialValues: publicServices,
    required: true,
  });
  if (prompts.isCancel(selectedPublicServices)) return;
  if (!selectedPublicServices.length) throw new Error("Select at least one public web service.");

  const confirmed = await prompts.confirm({ message: `Create and deploy ${repository}@${branch}?`, initialValue: false });
  if (prompts.isCancel(confirmed) || !confirmed) return;

  const created = asCreatedImport(await api.request("POST", "/github/imports", {
    ...selection,
    addons,
    public_services: selectedPublicServices,
  }));
  const progress = asProgress(await api.request("GET", `/github/imports/${encodeURIComponent(created.import_id)}`));
  prompts.note(progress.steps.map(step => `${step.service_name ?? "service"} · ${step.error_message ?? step.status}`).join("\n") || "Release queued", "Import started");
  return { projectId: created.project_id, environmentId: created.environment_id };
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object") throw new Error("Control plane returned an invalid GitHub import response.");
  return value as Record<string, unknown>;
}
function asArray<T>(value: unknown): T[] {
  if (!Array.isArray(value)) throw new Error("Control plane returned an invalid GitHub import list.");
  return value as T[];
}
function asPreview(value: unknown): Preview {
  const preview = asRecord(value);
  if ((preview.compose_source !== "repository" && preview.compose_source !== "generated") || !Array.isArray(preview.addons) || !Array.isArray(preview.services)) throw new Error("Control plane returned an invalid GitHub import preview.");
  return preview as unknown as Preview;
}
function asCreatedImport(value: unknown): CreatedImport {
  const created = asRecord(value);
  if (typeof created.import_id !== "string" || typeof created.project_id !== "string" || typeof created.environment_id !== "string") throw new Error("Control plane did not return the created project context.");
  return created as unknown as CreatedImport;
}
function asProgress(value: unknown): ImportProgress {
  const progress = asRecord(value);
  return { steps: Array.isArray(progress.steps) ? progress.steps as ImportProgress["steps"] : [] };
}
function previewSummary(preview: Preview): string {
  const source = preview.compose_source === "repository" ? "Repository Compose detected" : "Generated Compose proposal";
  const services = preview.services.map(service => `${service.name} · ${service.role}${service.is_public ? " · public" : " · private"}`);
  return [source, ...services].join("\n");
}
