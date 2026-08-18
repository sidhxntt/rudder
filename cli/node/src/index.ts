#!/usr/bin/env node
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import * as p from "@clack/prompts";
import { advisorRequest } from "./advisor.js";
import { authenticationGate } from "./auth-guard.js";
import { ApiClient, ApiError } from "./client.js";
import { loadConfig, mergeContext, saveConfig, type Context } from "./context.js";
import { completeGitHubLogin } from "./github-login.js";
import { formatServiceGraph, serviceGraph } from "./graph.js";
import { runGitHubImportWizard } from "./github-import-wizard.js";
import { canLaunchLauncher, runLauncher, runStatusMenu } from "./launcher.js";
import { CliCancellationError, CliStreamOutputError, CliUsageError } from "./errors.js";
import { fail, print, success, type Output } from "./output.js";
import { formatCompactStatus, toStatusAdvisorInput, type StatusRow } from "./status.js";

type Flags = Record<string, string | boolean>;
type State = { api: ApiClient; context: Context; credentials: { url?: string; token?: string }; flags: Flags; out: Output };
const booleanFlags = new Set(["json", "no-interactive", "yes", "follow", "build", "runtime", "production", "delete-volume", "help"]);
const valueFlags = new Set(["url", "project", "env", "service", "data", "commit", "deployment", "window", "branch", "repo", "port", "value", "idempotency-key", "path"]);

export { CliCancellationError, CliUsageError } from "./errors.js";
const usage = `rudder — Rudder control-plane CLI

Usage: rudder [--url URL] [--project ID|NAME] [--env ID|NAME] [--service ID|NAME] [--json] [--no-interactive] <command>
Commands: login logout whoami context project env service var deploy logs history rollback status metrics operation import domain advisor api`;

export function parseArgs(argv: string[]): { args: string[]; flags: Flags } {
  const args: string[] = [], flags: Flags = {};
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]!;
    if (!token.startsWith("--")) { args.push(token); continue; }
    const [key, value] = token.slice(2).split("=", 2);
    if (!booleanFlags.has(key) && !valueFlags.has(key)) throw new CliUsageError(`Unknown flag: --${key}.`);
    if (booleanFlags.has(key)) {
      if (value !== undefined && value !== "true" && value !== "false") throw new CliUsageError(`--${key} must be true or false.`);
      flags[key] = value === undefined || value === "true";
      continue;
    }
    if (value !== undefined && value !== "") { flags[key] = value; continue; }
    if (argv[i + 1] && !argv[i + 1]!.startsWith("--")) { flags[key] = argv[++i]!; continue; }
    throw new CliUsageError(`--${key} requires a value.`);
  }
  return { args, flags };
}
function stringFlag(flags: Flags, name: string): string | undefined { const v = flags[name]; return typeof v === "string" ? v : undefined; }
function requireNoPositionals(values: Array<string | undefined>, commandName: string): void {
  if (values.some(Boolean)) throw new CliUsageError(`${commandName} does not accept positional arguments.`);
}
function requireExactPositionals(values: string[], count: number, commandName: string): void {
  if (values.length !== count) throw new CliUsageError(`${commandName} requires exactly ${count} positional argument${count === 1 ? "" : "s"}.`);
}
function requireAtMostPositionals(values: string[], count: number, commandName: string): void {
  if (values.length > count) throw new CliUsageError(`${commandName} accepts at most ${count} positional argument${count === 1 ? "" : "s"}.`);
}
function directTarget(action: string | undefined, rest: string[], commandName: string): string | undefined {
  const values = [action, ...rest].filter((value): value is string => Boolean(value));
  requireAtMostPositionals(values, 1, commandName);
  return values[0];
}
function jsonBody(flags: Flags): unknown { const raw = stringFlag(flags, "data"); if (!raw) return undefined; try { return JSON.parse(raw); } catch { throw new CliUsageError("--data must contain JSON"); } }
function requireArg(args: string[], index: number, name: string): string { const value = args[index]; if (!value) throw new CliUsageError(`Missing ${name}.`); return value; }

export function exitCodeForError(error: unknown): number {
  if (error instanceof CliStreamOutputError) return exitCodeForError(error.cause);
  if (error instanceof CliUsageError) return 2;
  if (error instanceof CliCancellationError) return 130;
  return 1;
}
export function toErrorEnvelope(error: unknown): { code: string; message: string; details: Record<string, unknown> } {
  if (error instanceof ApiError && isErrorEnvelope(error.detail)) return error.detail;
  if (error instanceof CliUsageError) return { code: "usage", message: error.message, details: {} };
  if (error instanceof CliCancellationError) return { code: "cancelled", message: error.message, details: {} };
  const message = error instanceof Error ? error.message : String(error);
  return { code: error instanceof ApiError ? "api_error" : "runtime_error", message, details: error instanceof ApiError ? { status: error.status } : {} };
}
function isErrorEnvelope(value: unknown): value is { code: string; message: string; details: Record<string, unknown> } {
  return isRecord(value) && typeof value.code === "string" && typeof value.message === "string" && isRecord(value.details);
}
export function renderCliError(error: unknown, json: boolean): void {
  if (json) console.error(JSON.stringify(toErrorEnvelope(error)));
  else fail(error instanceof ApiError || error instanceof Error ? error.message : String(error));
}

async function resolve(state: State, kind: "project" | "environment" | "service", supplied?: string): Promise<string> {
  const wanted = supplied ?? state.context[kind]; if (!wanted) throw new CliUsageError(`No ${kind} selected. Use --${kind === "environment" ? "env" : kind} or \`rudder ${kind === "environment" ? "env" : kind} use\`.`);
  if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(wanted)) return wanted;
  const path = kind === "project" ? "/projects" : kind === "environment" ? `/projects/${await resolve(state, "project")}/environments` : `/environments/${await resolve(state, "environment")}/services`;
  const rows = await state.api.request("GET", path) as Array<Record<string, unknown>>;
  const byId = rows.find(row => row.id === wanted);
  if (byId && typeof byId.id === "string") return byId.id;
  const matches = rows.filter(row => row.name === wanted && typeof row.id === "string");
  if (!matches.length) throw new CliUsageError(`No ${kind} named ${wanted}.`);
  if (matches.length > 1) throw new CliUsageError(`${capitalize(kind)} name ${wanted} is ambiguous; use one of: ${matches.map(row => row.id).join(", ")}.`);
  return matches[0]!.id as string;
}
function capitalize(value: string): string { return value[0]!.toUpperCase() + value.slice(1); }
async function confirm(state: State, question: string): Promise<void> { if (state.flags.yes) return; if (state.flags["no-interactive"] || !process.stdin.isTTY) throw new CliUsageError(`${question} Pass --yes to confirm.`); const answer = await p.confirm({ message: question }); if (p.isCancel(answer) || !answer) { p.cancel("Operation cancelled."); throw new CliCancellationError(); } }
async function request(state: State, method: string, path: string, body?: unknown): Promise<unknown> { const result = await state.api.request(method, path, body); print(result, state.out); return result; }
async function streamOutput(state: State, path: string, source: "build" | "runtime"): Promise<void> {
  let emitted = false;
  try {
    const streamPath = `${path}${path.includes("?") ? "&" : "?"}follow=${Boolean(state.flags.follow)}`;
    for await (const line of state.api.stream(streamPath)) {
      print(state.out.json ? logRecord(line, source) : line, state.out);
      emitted = true;
    }
  } catch (error) {
    if (state.out.json && emitted) {
      print({ error: toErrorEnvelope(error) }, state.out);
      throw new CliStreamOutputError(error);
    }
    throw error;
  }
}
function logRecord(message: string, source: "build" | "runtime"): { timestamp: string; source: string; level: string; message: string } {
  const leadingLevel = message.match(/^\s*\[(debug|info|warn|warning|error)\]/i)?.[1]?.toLowerCase();
  const level = leadingLevel === "warning" ? "warn" : leadingLevel ?? "info";
  return { timestamp: new Date().toISOString(), source, level, message };
}

async function command(state: State, args: string[]): Promise<void> {
  const [noun, action, ...rest] = args;
  if (noun === "help" || noun === "--help" || state.flags.help || (!noun && !state.flags["no-interactive"])) { requireNoPositionals([action, ...rest], "help"); console.log(usage); return; }
  if (!noun) throw new CliUsageError("Missing command. Run `rudder help` for usage.");
  if (noun === "login") { requireNoPositionals([action, ...rest], "login"); if (state.flags["no-interactive"] || !process.stdin.isTTY) throw new CliUsageError("GitHub sign-in requires an interactive terminal. Set RUDDER_TOKEN for automation."); const result = await completeGitHubLogin({ api: state.api }); await saveAccessToken(state, result); if (!state.out.json) success(`Logged in to ${state.api.baseUrl}.`, state.out); return; }
  if (noun === "logout") { requireNoPositionals([action, ...rest], "logout"); discardSession(state); await saveConfig(state.context, state.credentials); success("Logged out.", state.out); return; }
  if (noun === "whoami") { requireNoPositionals([action, ...rest], "whoami"); return void await request(state, "GET", "/auth/me"); }
  if (noun === "context") { if (action === "show" || !action) { requireNoPositionals(rest, "context show"); return void print(state.context, state.out); } if (action === "clear") { requireNoPositionals(rest, "context clear"); state.context = {}; await saveConfig(state.context, state.credentials); success("Context cleared.", state.out); return; } throw new CliUsageError("context: show, clear"); }
  if (noun === "api") { const method = requireArg(args, 1, "HTTP method").toUpperCase(); const path = requireArg(args, 2, "API path"); requireNoPositionals(args.slice(3), "api"); return void await request(state, method, path, jsonBody(state.flags)); }
  if (noun === "project") return project(state, action, rest);
  if (noun === "env") return environment(state, action, rest);
  if (noun === "service") return service(state, action, rest);
  if (noun === "var") return variable(state, action, rest);
  if (noun === "deploy") { const id = await resolve(state, "service", directTarget(action, rest, "deploy")); const deployment = await state.api.request("POST", `/services/${id}/deploy`, stringFlag(state.flags, "commit") ? { commit_sha: stringFlag(state.flags, "commit") } : undefined) as { id?: string }; if (state.flags.follow && deployment.id) await streamOutput(state, `/deployments/${deployment.id}/build-log`, "build"); else print(deployment, state.out); return; }
  if (noun === "history") { const id = await resolve(state, "service", directTarget(action, rest, "history")); return void await request(state, "GET", `/services/${id}/deployments`); }
  if (noun === "rollback") { const id = directTarget(action, rest, "rollback"); if (!id) throw new CliUsageError("Missing deployment id."); await confirm(state, `Roll back to deployment ${id}?`); return void await request(state, "POST", `/deployments/${id}/rollback`); }
  if (noun === "logs") {
    if (state.flags.build && state.flags.runtime) throw new CliUsageError("Choose either --build or --runtime for logs, not both.");
    const id = await resolve(state, "service", directTarget(action, rest, "logs"));
    if (state.flags.runtime) {
      await streamOutput(state, `/services/${id}/runtime-log`, "runtime");
      return;
    }
    const deployments = await state.api.request("GET", `/services/${id}/deployments`) as Array<{ id?: string }>;
    const deployment = stringFlag(state.flags, "deployment") ?? deployments[0]?.id;
    if (!deployment) throw new CliUsageError("No deployments found. Use `rudder deploy` first.");
    await streamOutput(state, `/deployments/${deployment}/build-log`, "build");
    return;
  }
  if (noun === "metrics") { const id = await resolve(state, "service", directTarget(action, rest, "metrics")); const window = stringFlag(state.flags, "window") ?? "1h"; return void await request(state, "GET", `/services/${id}/metrics?window=${encodeURIComponent(window)}`); }
  if (noun === "status" || noun === "ps") {
    requireNoPositionals([action, ...rest], noun);
    const rows = await loadStatusRows(state);
    if (state.out.json) return void print(rows, state.out);
    console.log(formatCompactStatus(rows));
    return;
  }
  if (noun === "operation") return operation(state, action, rest);
  if (noun === "import") return githubImport(state, action, rest);
  if (noun === "domain") return domain(state, action, rest);
  if (noun === "advisor") return advisor(state, action, rest);
  throw new CliUsageError(`Unknown command: ${noun}. Run \`rudder help\`.`);
}

async function saveAccessToken(state: State, result: Record<string, unknown>): Promise<void> {
  const token = result.access_token;
  if (typeof token !== "string") throw new Error("Control plane did not return an access token.");
  state.credentials.token = token;
  state.api = new ApiClient(state.api.baseUrl, token);
  await saveConfig(state.context, state.credentials);
}
async function loadStatusRows(state: State): Promise<StatusRow[]> {
  const environment = await resolve(state, "environment");
  const services = await state.api.request("GET", `/environments/${environment}/services`) as Array<{ id: string; name: string; kind?: string | null }>;
  return Promise.all(services.map(async service => ({
    service,
    deployments: await state.api.request("GET", `/services/${service.id}/deployments`) as StatusRow["deployments"],
    instances: await state.api.request("GET", `/services/${service.id}/instances`) as StatusRow["instances"],
  })));
}
async function explainStatus(state: State, rows: StatusRow[]): Promise<void> {
  console.log(formatCompactStatus(rows));
  try {
    const result = await advisorRequest(state.api, "diagnose", undefined, toStatusAdvisorInput(rows));
    if (!isRecord(result) || result.enabled !== true || typeof result.diagnosis !== "string") {
      console.log("\nAI summary unavailable: configure OPENAI_API_KEY in the control plane.");
      return;
    }
    console.log(`\nAI status summary\n${result.diagnosis}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : "The control plane did not return a summary.";
    console.log(`\nAI summary unavailable: ${message}`);
  }
}
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
export function discardSession(session: { api: ApiClient; credentials: { url?: string; token?: string } }): void {
  session.credentials.token = undefined;
  session.api = new ApiClient(session.api.baseUrl);
}
export function isDirectExecution(entry: string | undefined, moduleFile: string): boolean {
  if (!entry) return false;
  try {
    return realpathSync(entry) === realpathSync(moduleFile);
  } catch {
    return false;
  }
}
async function requireAuthentication(state: State, announce = true): Promise<void> {
  const gate = authenticationGate({
    hasToken: Boolean(state.credentials.token || process.env.RUDDER_TOKEN),
    noInteractive: Boolean(state.flags["no-interactive"]),
    isTTY: Boolean(process.stdin.isTTY),
  });
  if (gate === "ready") return;
  if (gate === "noninteractive-error") {
    throw new CliUsageError("Sign in first with `rudder login`, or set RUDDER_TOKEN for automation.");
  }
  await saveAccessToken(state, await completeGitHubLogin({ api: state.api }));
  if (announce) success(`Logged in to ${state.api.baseUrl}.`, state.out);
}
export async function chooseProjectEnvironment(state: State): Promise<string | void> {
  const projects = selectOptions(await state.api.request("GET", "/projects"), "project");
  if (!projects.length) throw new Error("No projects found. Create one with `rudder project create`.");
  const project = await p.select({ message: "Choose project", options: projects });
  if (p.isCancel(project)) {
    p.cancel("Project selection cancelled.");
    throw new CliCancellationError();
  }

  const environments = selectOptions(
    await state.api.request("GET", `/projects/${project}/environments`),
    "environment",
    environment => localEnvironmentLabel(environment, state.api.baseUrl),
  );
  if (!environments.length) throw new Error("No environments found. Create one with `rudder env create`.");
  const environment = await p.select({ message: "Choose environment", options: environments });
  if (p.isCancel(environment)) {
    p.cancel("Environment selection cancelled.");
    throw new CliCancellationError();
  }

  state.context.project = project;
  state.context.environment = environment;
  delete state.context.service;
  await saveConfig(state.context, state.credentials);
  const projectLabel = projects.find(option => option.value === project)?.label ?? project;
  const environmentLabel = environments.find(option => option.value === environment)?.label ?? environment;
  return `Using ${projectLabel} / ${environmentLabel}`;
}
/** Select a service on demand so Logs is usable immediately after project onboarding. */
export async function chooseServiceForLogs(state: State): Promise<string | void> {
  if (state.context.service) return resolve(state, "service");
  const environment = await resolve(state, "environment");
  const services = selectOptions(await state.api.request("GET", `/environments/${environment}/services`), "service");
  if (!services.length) throw new Error("No services found. Deploy a repository first.");
  const service = await p.select({ message: "Choose a service for logs", options: services });
  if (p.isCancel(service)) {
    p.cancel("Service selection cancelled.");
    throw new CliCancellationError();
  }
  state.context.service = service;
  await saveConfig(state.context, state.credentials);
  return service;
}
/** Establish the first project/environment context before operational commands are available. */
export async function chooseInitialProject(state: State): Promise<string | void> {
  const projects = selectOptions(recentProjects(await state.api.request("GET", "/projects")), "project");
  const choice = await p.select<string>({
    message: "Choose a project",
    options: [
      ...projects,
      { value: "create-from-github", label: "Create new from GitHub", hint: "Import a repository and deploy it" },
      { value: "exit", label: "Exit" },
    ],
  });
  if (p.isCancel(choice)) {
    p.cancel("Project selection cancelled.");
    throw new CliCancellationError();
  }
  if (choice === "exit") return;

  if (choice === "create-from-github") {
    const created = await runGitHubImportWizard({ api: state.api });
    if (!created) return;
    state.context = { project: created.projectId, environment: created.environmentId };
    await saveConfig(state.context, state.credentials);
    return "Project created from GitHub.";
  }

  const rawEnvironments = await state.api.request("GET", `/projects/${choice}/environments`);
  const environments = selectOptions(rawEnvironments, "environment", environment => localEnvironmentLabel(environment, state.api.baseUrl));
  if (!environments.length) throw new Error("This project has no environments.");
  const environment = preferredEnvironment(rawEnvironments, environments);
  state.context = { project: choice, environment };
  await saveConfig(state.context, state.credentials);
  const projectLabel = projects.find(option => option.value === choice)?.label ?? choice;
  const environmentLabel = environments.find(option => option.value === environment)?.label ?? environment;
  return `Using ${projectLabel} / ${environmentLabel}`;
}
function selectOptions(
  value: unknown,
  kind: string,
  labelFor = (row: Record<string, unknown>) => typeof row.name === "string" ? row.name : undefined,
): Array<{ value: string; label: string }> {
  if (!Array.isArray(value)) throw new Error(`Could not load ${kind}s.`);
  return value.flatMap(row => {
    if (!row || typeof row !== "object") return [];
    const record = row as Record<string, unknown>;
    const { id } = record;
    const label = labelFor(record);
    return typeof id === "string" ? [{ value: id, label: label ?? id }] : [];
  });
}
function localEnvironmentLabel(environment: Record<string, unknown>, baseUrl: string): string | undefined {
  const name = typeof environment.name === "string" ? environment.name : undefined;
  try {
    const hostname = new URL(baseUrl).hostname;
    if (environment.is_production === true && (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1")) return "development";
  } catch {
    // Keep the API label when a custom endpoint is not a valid URL.
  }
  return name;
}
function preferredEnvironment(raw: unknown, options: Array<{ value: string; label: string }>): string {
  if (Array.isArray(raw)) {
    const production = raw.find(row => row && typeof row === "object" && (row as Record<string, unknown>).is_production === true) as Record<string, unknown> | undefined;
    if (typeof production?.id === "string") return production.id;
  }
  return options[0]!.value;
}
function recentProjects(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return [...value].sort((left, right) => {
    const leftCreated = left && typeof left === "object" && typeof (left as Record<string, unknown>).created_at === "string"
      ? Date.parse((left as Record<string, string>).created_at)
      : Number.NEGATIVE_INFINITY;
    const rightCreated = right && typeof right === "object" && typeof (right as Record<string, unknown>).created_at === "string"
      ? Date.parse((right as Record<string, string>).created_at)
      : Number.NEGATIVE_INFINITY;
    return rightCreated - leftCreated;
  });
}
async function project(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (action === "list") { requireNoPositionals(a, "project list"); return void await request(s, "GET", "/projects"); }
  if (action === "create") { requireExactPositionals(a, 1, "project create"); return void await request(s, "POST", "/projects", { name: a[0] }); }
  if (!action || !["get", "use", "settings", "delete"].includes(action)) throw new CliUsageError("project: list, create, get, use, settings, delete");
  requireExactPositionals(a, 1, `project ${action}`);
  const id = await resolve(s, "project", a[0]);
  if (action === "use") { s.context.project = id; delete s.context.environment; delete s.context.service; await saveConfig(s.context, s.credentials); return void success("Project selected.", s.out); }
  if (action === "delete") { await confirm(s, `Delete project ${id} and all its data?`); return void await request(s, "DELETE", `/projects/${id}`); }
  if (action === "get") return void await request(s, "GET", `/projects/${id}`);
  return void await request(s, "PATCH", `/projects/${id}`, jsonBody(s.flags));
}
async function environment(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (!action || !["list", "create", "get", "use", "clone", "settings", "delete"].includes(action)) throw new CliUsageError("env: list, create, get, use, clone, settings, delete");
  if (action === "list") requireNoPositionals(a, "env list");
  else if (action === "create") requireExactPositionals(a, 1, "env create");
  else if (action === "clone") requireExactPositionals(a, 2, "env clone");
  else requireExactPositionals(a, 1, `env ${action}`);
  const projectId = await resolve(s, "project");
  if (action === "list") return void await request(s, "GET", `/projects/${projectId}/environments`);
  if (action === "create") return void await request(s, "POST", `/projects/${projectId}/environments`, { name: a[0], is_production: Boolean(s.flags.production) });
  const id = await resolve(s, "environment", a[0]);
  if (action === "use") { s.context.environment = id; delete s.context.service; await saveConfig(s.context, s.credentials); return void success("Environment selected.", s.out); }
  if (action === "clone") return void await request(s, "POST", `/environments/${id}/clone`, { name: a[1] });
  if (action === "delete") { await confirm(s, `Destroy environment ${id}?`); return void await request(s, "DELETE", `/environments/${id}`); }
  if (action === "get") return void await request(s, "GET", `/environments/${id}`);
  return void await request(s, "PATCH", `/environments/${id}`, jsonBody(s.flags));
}
async function service(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (!action || !["list", "graph", "create", "template", "get", "use", "settings", "delete"].includes(action)) throw new CliUsageError("service: list, graph, create, template, get, use, settings, delete");
  if (action === "list" || action === "graph") requireNoPositionals(a, `service ${action}`);
  else if (action === "create" || action === "template" || action === "get" || action === "use" || action === "settings" || action === "delete") requireExactPositionals(a, 1, `service ${action}`);
  const env = await resolve(s, "environment");
  if (action === "list") return void await request(s, "GET", `/environments/${env}/services`);
  if (action === "graph") { const services = await s.api.request("GET", `/environments/${env}/services`) as Array<{ id: string; name: string; source_repo: string | null; build_config: Record<string, unknown> }>; const graph = serviceGraph(services); return void (s.out.json ? print(graph, s.out) : console.log(formatServiceGraph(graph))); }
  if (action === "create") return void await request(s, "POST", `/environments/${env}/services`, jsonBody(s.flags) ?? { name: a[0], source_repo: stringFlag(s.flags, "repo"), source_branch: stringFlag(s.flags, "branch") ?? "main", container_port: Number(stringFlag(s.flags, "port") ?? 8080) });
  if (action === "template") return void await request(s, "POST", `/environments/${env}/database-templates/${a[0]}`);
  const id = await resolve(s, "service", a[0]);
  if (action === "use") { s.context.service = id; await saveConfig(s.context, s.credentials); return void success("Service selected.", s.out); }
  if (action === "get") return void await request(s, "GET", `/services/${id}`);
  if (action === "settings") return void await request(s, "PATCH", `/services/${id}`, jsonBody(s.flags));
  await confirm(s, `Delete service ${id}?`); return void await request(s, "DELETE", `/services/${id}${s.flags["delete-volume"] ? "?confirm_volume_deletion=true" : ""}`);
}
async function variable(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (action === "list") requireNoPositionals(a, "var list");
  else if (action === "set") requireExactPositionals(a, stringFlag(s.flags, "value") ? 1 : 2, "var set");
  else if (action === "unset") requireExactPositionals(a, 1, "var unset");
  else throw new CliUsageError("var: list, set KEY VALUE, unset KEY");
  const id = await resolve(s, "service", stringFlag(s.flags, "service"));
  if (action === "list") return void await request(s, "GET", `/services/${id}/variables`);
  const key = a[0]!;
  if (action === "set") return void await request(s, "PUT", `/services/${id}/variables/${encodeURIComponent(key)}`, { value: stringFlag(s.flags, "value") ?? a[1] });
  await confirm(s, `Unset ${key}?`); return void await request(s, "DELETE", `/services/${id}/variables/${encodeURIComponent(key)}`);
}
async function operation(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (action === "list" || action === "update") requireAtMostPositionals(a, 1, `operation ${action}`);
  else throw new CliUsageError("operation: list, update");
  const id = await resolve(s, "service", a[0]);
  if (action === "list") return void await request(s, "GET", `/services/${id}/operations?format=envelope`);
  return void await request(s, "PATCH", `/services/${id}/operations`, jsonBody(s.flags));
}
async function githubImport(s: State, action: string | undefined, a: string[]): Promise<void> {
  const routes: Record<string, string> = { status: "/github/import/status", templates: "/github/import/templates", installations: "/github/import/installations" };
  if (action && routes[action]) { requireNoPositionals(a, `import ${action}`); return void await request(s, "GET", routes[action]); }
  if (action === "repositories") { requireExactPositionals(a, 1, "import repositories"); return void await request(s, "GET", `/github/import/repositories?installation_id=${encodeURIComponent(a[0]!)}`); }
  if (action === "branches") { requireExactPositionals(a, 2, "import branches"); return void await request(s, "GET", `/github/import/branches?installation_id=${encodeURIComponent(a[0]!)}&repository=${encodeURIComponent(a[1]!)}`); }
  if (action === "preview") { requireNoPositionals(a, "import preview"); return void await request(s, "POST", "/github/import/preview", jsonBody(s.flags)); }
  if (action === "create") { requireNoPositionals(a, "import create"); await confirm(s, "Create project and deploy imported repository?"); return void await request(s, "POST", "/github/imports", jsonBody(s.flags)); }
  if (action === "get") { requireExactPositionals(a, 1, "import get"); return void await request(s, "GET", `/github/imports/${a[0]}`); }
  throw new CliUsageError("import: status, templates, installations, repositories, branches, preview, create, get");
}
async function domain(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (!action || !["list", "create", "settings", "delete"].includes(action)) throw new CliUsageError("domain: list, create, settings, delete");
  if (action === "list" || action === "create") requireNoPositionals(a, `domain ${action}`); else requireExactPositionals(a, 1, `domain ${action}`);
  const env = await resolve(s, "environment");
  if (action === "list") return void await request(s, "GET", `/environments/${env}/domains`);
  if (action === "create") return void await request(s, "POST", `/environments/${env}/domains`, jsonBody(s.flags));
  if (action === "delete") { await confirm(s, `Delete domain ${a[0]}?`); return void await request(s, "DELETE", `/domains/${a[0]}`); }
  return void await request(s, "PATCH", `/domains/${a[0]}`, jsonBody(s.flags));
}
async function advisor(s: State, action: string | undefined, a: string[]): Promise<void> {
  if (action === "diagnose") { requireNoPositionals(a, "advisor diagnose"); const result = await advisorRequest(s.api, "diagnose", undefined, jsonBody(s.flags)); if (s.out.json) return void print(result, s.out); console.log("Model-generated diagnosis (may be incomplete):"); return void print(result, s.out); }
  if (action === "scan") { requireNoPositionals(a, "advisor scan"); const environment = await resolve(s, "environment"); const path = stringFlag(s.flags, "path"); if (!path) throw new CliUsageError("advisor scan requires --path."); return void print(await advisorRequest(s.api, action, environment, { repository_path: path }), s.out); }
  if (action === "accept") { requireNoPositionals(a, "advisor accept"); const environment = await resolve(s, "environment"); const body = jsonBody(s.flags); if (!body) throw new CliUsageError("advisor accept requires exactly one proposal in --data JSON."); return void print(await advisorRequest(s.api, action, environment, body), s.out); }
  throw new CliUsageError("advisor: scan --path PATH, accept --data JSON, diagnose --data JSON");
}

export async function main(): Promise<void> {
  const parsed = parseArgs(process.argv.slice(2));
  if (parsed.flags.json) parsed.flags["no-interactive"] = true;
  const saved = await loadConfig();
  const context = mergeContext(saved.context, { project: stringFlag(parsed.flags, "project"), environment: stringFlag(parsed.flags, "env"), service: stringFlag(parsed.flags, "service") });
  const url = stringFlag(parsed.flags, "url") ?? process.env.RUDDER_URL ?? saved.credentials.url ?? "http://localhost:8000";
  const state: State = { api: new ApiClient(url, process.env.RUDDER_TOKEN ?? saved.credentials.token), context, credentials: { ...saved.credentials, url }, flags: parsed.flags, out: { json: Boolean(parsed.flags.json) } };
  const noun = parsed.args[0];
  const authenticated = Boolean(state.credentials.token || process.env.RUDDER_TOKEN);
  const launch = canLaunchLauncher({ hasArgs: Boolean(noun), json: Boolean(parsed.flags.json), noInteractive: Boolean(parsed.flags["no-interactive"]), stdinTTY: Boolean(process.stdin.isTTY), stdoutTTY: Boolean(process.stdout.isTTY) });
  if (launch) {
    await runLauncher({
      authenticated,
      projectSelected: authenticated && Boolean(state.context.project && state.context.environment),
      actions: {
        signIn: () => requireAuthentication(state, false),
        chooseProject: () => chooseInitialProject(state),
        deploy: () => command(state, ["deploy"]),
        status: async () => {
          const rows = await loadStatusRows(state);
          await runStatusMenu({
            compact: async () => console.log(formatCompactStatus(rows)),
            detailed: async () => print(rows, state.out),
            summary: async () => explainStatus(state, rows),
          });
        },
        logs: async () => {
          const service = await chooseServiceForLogs(state);
          if (!service) return;
          const spinner = p.spinner();
          spinner.start("Loading build logs");
          try {
            await command(state, ["logs", service]);
            spinner.stop("Build logs loaded");
          } catch (error) {
            spinner.stop("Build logs unavailable");
            throw error;
          }
        },
        services: () => command(state, ["service", "list"]),
        variables: () => command(state, ["var", "list"]),
        advisor: () => command(state, ["advisor", "diagnose"]),
        signOut: () => command(state, ["logout"]),
      },
    });
    return;
  }
  if (![undefined, "help", "--help", "login", "logout"].includes(noun)) await requireAuthentication(state);
  await command(state, parsed.args);
}
if (isDirectExecution(process.argv[1], fileURLToPath(import.meta.url))) main().catch((error: unknown) => {
  const json = process.argv.slice(2).some(token => token === "--json" || token === "--json=true");
  if (!(error instanceof CliStreamOutputError)) renderCliError(error, json);
  process.exitCode = exitCodeForError(error);
});
