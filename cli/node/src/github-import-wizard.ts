import * as clack from "@clack/prompts";
import { CliCancellationError } from "./errors.js";

type Api = { baseUrl?: string; request(method: string, path: string, body?: unknown): Promise<unknown> };
type PromptApi = Pick<typeof clack, "select" | "multiselect" | "confirm" | "isCancel" | "note" | "spinner">;

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
  const status = asRecord(await loading(prompts, "Checking GitHub import", "GitHub import ready", () => api.request("GET", "/github/import/status")));
  if (status.configured !== true) throw new Error(typeof status.message === "string" ? status.message : "GitHub import is not enabled here.");

  const templates = asArray<Template>(await loading(prompts, "Loading starter templates", "Starter templates ready", () => api.request("GET", "/github/import/templates")));
  const source = await prompts.select<"repository" | string>({
    message: "Choose a source",
    options: [
      { value: "repository", label: "Repository Compose", hint: "Use compose.yaml from your branch" },
      ...templates.map(template => ({ value: template.id, label: template.name, hint: template.description })),
    ],
  });
  if (prompts.isCancel(source)) throw new CliCancellationError();
  const templateId = source === "repository" ? null : source;

  const installations = asArray<Installation>(await loading(prompts, "Loading GitHub connections", "GitHub connections ready", () => api.request("GET", "/github/import/installations")));
  if (!installations.length) throw new Error("No GitHub App installation is connected. Install the Rudder GitHub App, then run `rudder` again.");
  const installationId = await prompts.select<number>({
    message: "Choose GitHub connection",
    options: installations.map(installation => ({
      value: installation.id,
      label: installation.account_login,
      hint: installation.repository_selection === "all" ? "all repositories" : "selected repositories",
    })),
  });
  if (prompts.isCancel(installationId)) throw new CliCancellationError();

  const repositories = asArray<Repository>(await loading(prompts, "Loading repositories", "Repositories ready", () => api.request("GET", `/github/import/repositories?installation_id=${installationId}`)));
  if (!repositories.length) throw new Error("This GitHub connection has no repositories available to Rudder.");
  const repository = await prompts.select<string>({
    message: "Choose repository",
    options: repositories.map(item => ({ value: item.full_name, label: item.full_name, hint: item.private ? "private" : "public" })),
  });
  if (prompts.isCancel(repository)) throw new CliCancellationError();

  const selectedRepository = repositories.find(item => item.full_name === repository);
  const branches = asArray<string>(await loading(prompts, "Loading branches", "Branches ready", () => api.request("GET", `/github/import/branches?installation_id=${installationId}&repository=${encodeURIComponent(repository)}`)));
  if (!branches.length) throw new Error("Rudder could not find a branch for this repository.");
  const branch = await prompts.select<string>({
    message: "Choose branch",
    options: branches.map(item => ({ value: item, label: item })),
    initialValue: selectedRepository?.default_branch && branches.includes(selectedRepository.default_branch) ? selectedRepository.default_branch : branches[0],
  });
  if (prompts.isCancel(branch)) throw new CliCancellationError();

  const selection = { installation_id: installationId, repository, branch, template_id: templateId };
  const preview = asPreview(await loading(prompts, `Inspecting ${repository}@${branch}`, "Release inspected", () => api.request("POST", "/github/import/preview", selection)));
  prompts.note(previewSummary(preview), "Review detected release");

  const addons = preview.compose_source === "generated" && preview.addons.length
    ? await prompts.multiselect<string>({
      message: "Select private add-ons",
      options: preview.addons.map(addon => ({ value: addon, label: addon })),
      initialValues: preview.addons,
    })
    : [];
  if (prompts.isCancel(addons)) throw new CliCancellationError();

  const publicServices = preview.services.filter(service => service.role === "web" && service.is_public).map(service => service.name);
  if (!publicServices.length) throw new Error("The reviewed release has no public web service to deploy.");
  const selectedPublicServices = await prompts.multiselect<string>({
    message: "Expose public services",
    options: publicServices.map(name => ({ value: name, label: name })),
    initialValues: publicServices,
    required: true,
  });
  if (prompts.isCancel(selectedPublicServices)) throw new CliCancellationError();
  if (!selectedPublicServices.length) throw new Error("Select at least one public web service.");

  const confirmed = await prompts.confirm({ message: `Create and deploy ${repository}@${branch}?`, initialValue: false });
  if (prompts.isCancel(confirmed)) throw new CliCancellationError();
  if (!confirmed) return undefined;

  const created = asCreatedImport(await loading(prompts, "Creating release", "Release created", () => api.request("POST", "/github/imports", {
    ...selection,
    addons,
    public_services: selectedPublicServices,
  })));
  const progress = asProgress(await loading(prompts, "Reading deployment progress", "Deployment progress ready", () => api.request("GET", `/github/imports/${encodeURIComponent(created.import_id)}`)));
  const progressText = progress.steps.map(step => `${step.service_name ?? "service"} · ${step.status}${step.error_message ? ` · ${step.error_message}` : ""}`).join("\n") || "Release queued";
  prompts.note(`${progressText}\n\nOpen in web: ${workspaceUrl(api.baseUrl, created.project_id, created.environment_id)}`, "Import started");
  return { projectId: created.project_id, environmentId: created.environment_id };
}

async function loading<T>(prompts: PromptApi, active: string, complete: string, work: () => Promise<T>): Promise<T> {
  const spinner = prompts.spinner();
  spinner.start(active);
  try {
    const result = await work();
    spinner.stop(complete);
    return result;
  } catch (error) {
    spinner.stop(`${active} failed`);
    throw error;
  }
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
function workspaceUrl(apiBaseUrl: string | undefined, projectId: string, environmentId: string): string {
  const fallback = "http://localhost:3000";
  let web: URL;
  try {
    web = new URL(process.env.RUDDER_WEB_URL ?? apiBaseUrl ?? fallback);
  } catch {
    web = new URL(fallback);
  }
  if ((web.hostname === "localhost" || web.hostname === "127.0.0.1") && web.port === "8000") web.port = "3000";
  return new URL(`/projects/${encodeURIComponent(projectId)}/environments/${encodeURIComponent(environmentId)}`, web).toString();
}
