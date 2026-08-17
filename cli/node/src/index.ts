#!/usr/bin/env node
import * as p from "@clack/prompts";
import { advisorRequest } from "./advisor.js";
import { authenticationGate } from "./auth-guard.js";
import { commandTarget } from "./command-target.js";
import { ApiClient, ApiError } from "./client.js";
import { loadConfig, mergeContext, saveConfig, type Context } from "./context.js";
import { completeGitHubLogin } from "./github-login.js";
import { formatServiceGraph, serviceGraph } from "./graph.js";
import { runLauncher } from "./launcher.js";
import { fail, print, success, type Output } from "./output.js";

type Flags = Record<string, string | boolean>;
type State = { api: ApiClient; context: Context; credentials: { url?: string; token?: string }; flags: Flags; out: Output };
const usage = `rudder — Rudder control-plane CLI

Usage: rudder [--url URL] [--project ID|NAME] [--env ID|NAME] [--service ID|NAME] [--json] [--no-interactive] <command>
Commands: login logout whoami context project env service var deploy logs history rollback status metrics operation import domain advisor api`;

function parse(argv: string[]): { args: string[]; flags: Flags } {
  const args: string[] = [], flags: Flags = {};
  for (let i = 0; i < argv.length; i++) { const token = argv[i]!; if (!token.startsWith("--")) { args.push(token); continue; } const [key, value] = token.slice(2).split("=", 2); if (value !== undefined) flags[key] = value; else if (argv[i + 1] && !argv[i + 1]!.startsWith("--")) flags[key] = argv[++i]!; else flags[key] = true; }
  return { args, flags };
}
function stringFlag(flags: Flags, name: string): string | undefined { const v = flags[name]; return typeof v === "string" ? v : undefined; }
function jsonBody(flags: Flags): unknown { const raw = stringFlag(flags, "data"); if (!raw) return undefined; try { return JSON.parse(raw); } catch { throw new Error("--data must contain JSON"); } }
function requireArg(args: string[], index: number, name: string): string { const value = args[index]; if (!value) throw new Error(`Missing ${name}.`); return value; }

async function resolve(state: State, kind: "project" | "environment" | "service", supplied?: string): Promise<string> {
  const wanted = supplied ?? state.context[kind]; if (!wanted) throw new Error(`No ${kind} selected. Use --${kind === "environment" ? "env" : kind} or \`rudder ${kind === "environment" ? "env" : kind} use\`.`);
  if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(wanted)) return wanted;
  const path = kind === "project" ? "/projects" : kind === "environment" ? `/projects/${await resolve(state, "project")}/environments` : `/environments/${await resolve(state, "environment")}/services`;
  const rows = await state.api.request("GET", path) as Array<Record<string, unknown>>;
  const found = rows.find(row => row.name === wanted || row.id === wanted); if (!found || typeof found.id !== "string") throw new Error(`No ${kind} named ${wanted}.`); return found.id;
}
async function confirm(state: State, question: string): Promise<void> { if (state.flags.yes) return; if (state.flags["no-interactive"] || !process.stdin.isTTY) throw new Error(`${question} Pass --yes to confirm.`); const answer = await p.confirm({ message: question }); if (p.isCancel(answer) || !answer) throw new Error("Aborted."); }
async function request(state: State, method: string, path: string, body?: unknown): Promise<unknown> { const result = await state.api.request(method, path, body); print(result, state.out); return result; }

async function command(state: State, args: string[]): Promise<void> {
  const [noun, action, ...rest] = args;
  if (!noun || noun === "help" || noun === "--help") { console.log(usage); return; }
  if (noun === "login") { if (state.flags["no-interactive"] || !process.stdin.isTTY) throw new Error("GitHub sign-in requires an interactive terminal. Set RUDDER_TOKEN for automation."); const result = await completeGitHubLogin({ api: state.api }); await saveAccessToken(state, result); if (!state.out.json) success(`Logged in to ${state.api.baseUrl}.`, state.out); return; }
  if (noun === "logout") { state.credentials.token = undefined; await saveConfig(state.context, state.credentials); success("Logged out.", state.out); return; }
  if (noun === "whoami") return void await request(state, "GET", "/auth/me");
  if (noun === "context") { if (action === "show" || !action) return void print(state.context, state.out); if (action === "clear") { state.context = {}; await saveConfig(state.context, state.credentials); success("Context cleared.", state.out); return; } }
  if (noun === "api") { const method = requireArg(args, 1, "HTTP method").toUpperCase(); const path = requireArg(args, 2, "API path"); return void await request(state, method, path, jsonBody(state.flags)); }
  if (noun === "project") return project(state, action, rest);
  if (noun === "env") return environment(state, action, rest);
  if (noun === "service") return service(state, action, rest);
  if (noun === "var") return variable(state, action, rest);
  if (noun === "deploy") { const id = await resolve(state, "service", commandTarget(action, rest)); const deployment = await state.api.request("POST", `/services/${id}/deploy`, stringFlag(state.flags, "commit") ? { commit_sha: stringFlag(state.flags, "commit") } : undefined) as { id?: string }; if (state.flags.follow && deployment.id) for await (const line of state.api.stream(`/deployments/${deployment.id}/build-log`)) print(state.out.json ? { log: line } : line, state.out); else print(deployment, state.out); return; }
  if (noun === "history") { const id = await resolve(state, "service", commandTarget(action, rest)); return void await request(state, "GET", `/services/${id}/deployments`); }
  if (noun === "rollback") { const id = commandTarget(action, rest); if (!id) throw new Error("Missing deployment id."); await confirm(state, `Roll back to deployment ${id}?`); return void await request(state, "POST", `/deployments/${id}/rollback`); }
  if (noun === "logs") { const id = await resolve(state, "service", commandTarget(action, rest)); if (!state.flags.follow) { const deployments = await state.api.request("GET", `/services/${id}/deployments`) as Array<{ id?: string }>; const deployment = stringFlag(state.flags, "deployment") ?? deployments[0]?.id; if (!deployment) throw new Error("No deployments found. Use `rudder deploy` first."); for await (const line of state.api.stream(`/deployments/${deployment}/build-log`)) print(state.out.json ? { log: line } : line, state.out); return; } for await (const line of state.api.stream(`/services/${id}/runtime-log`)) print(state.out.json ? { log: line } : line, state.out); return; }
  if (noun === "metrics") { const id = await resolve(state, "service", commandTarget(action, rest)); const window = stringFlag(state.flags, "window") ?? "1h"; return void await request(state, "GET", `/services/${id}/metrics?window=${encodeURIComponent(window)}`); }
  if (noun === "status" || noun === "ps") { const environment = await resolve(state, "environment"); const services = await state.api.request("GET", `/environments/${environment}/services`) as Array<{ id: string; name: string }>; const rows = await Promise.all(services.map(async service => ({ service, deployments: await state.api.request("GET", `/services/${service.id}/deployments`), instances: await state.api.request("GET", `/services/${service.id}/instances`) }))); return void print(rows, state.out); }
  if (noun === "operation") return operation(state, action, rest);
  if (noun === "import") return githubImport(state, action, rest);
  if (noun === "domain") return domain(state, action, rest);
  if (noun === "advisor") return advisor(state, action);
  throw new Error(`Unknown command: ${noun}. Run \`rudder help\`.`);
}

async function saveAccessToken(state: State, result: Record<string, unknown>): Promise<void> {
  const token = result.access_token;
  if (typeof token !== "string") throw new Error("Control plane did not return an access token.");
  state.credentials.token = token;
  state.api = new ApiClient(state.api.baseUrl, token);
  await saveConfig(state.context, state.credentials);
}
async function requireAuthentication(state: State): Promise<void> {
  const gate = authenticationGate({
    hasToken: Boolean(state.credentials.token || process.env.RUDDER_TOKEN),
    noInteractive: Boolean(state.flags["no-interactive"]),
    isTTY: Boolean(process.stdin.isTTY),
  });
  if (gate === "ready") return;
  if (gate === "noninteractive-error") {
    throw new Error("Sign in first with `rudder login`, or set RUDDER_TOKEN for automation.");
  }
  await saveAccessToken(state, await completeGitHubLogin({ api: state.api }));
  success(`Logged in to ${state.api.baseUrl}.`, state.out);
}
async function chooseProjectEnvironment(state: State): Promise<void> {
  const projects = selectOptions(await state.api.request("GET", "/projects"), "project");
  if (!projects.length) throw new Error("No projects found. Create one with `rudder project create`.");
  const project = await p.select({ message: "Choose project", options: projects });
  if (p.isCancel(project)) { p.cancel("Selection cancelled."); return; }

  const environments = selectOptions(await state.api.request("GET", `/projects/${project}/environments`), "environment");
  if (!environments.length) throw new Error("No environments found. Create one with `rudder env create`.");
  const environment = await p.select({ message: "Choose environment", options: environments });
  if (p.isCancel(environment)) { p.cancel("Selection cancelled."); return; }

  await command(state, ["project", "use", project]);
  await command(state, ["env", "use", environment]);
}
function selectOptions(value: unknown, kind: string): Array<{ value: string; label: string }> {
  if (!Array.isArray(value)) throw new Error(`Could not load ${kind}s.`);
  return value.flatMap(row => {
    if (!row || typeof row !== "object") return [];
    const { id, name } = row as { id?: unknown; name?: unknown };
    return typeof id === "string" ? [{ value: id, label: typeof name === "string" ? name : id }] : [];
  });
}
async function project(s: State, action: string | undefined, a: string[]): Promise<void> { if (action === "list") return void await request(s, "GET", "/projects"); if (action === "create") return void await request(s, "POST", "/projects", { name: requireArg(a, 0, "project name") }); const id = await resolve(s, "project", a[0]); if (action === "use") { s.context.project = id; delete s.context.environment; delete s.context.service; await saveConfig(s.context, s.credentials); return void success("Project selected.", s.out); } if (action === "delete") { await confirm(s, `Delete project ${id} and all its data?`); return void await request(s, "DELETE", `/projects/${id}`); } if (action === "get") return void await request(s, "GET", `/projects/${id}`); if (action === "settings") return void await request(s, "PATCH", `/projects/${id}`, jsonBody(s.flags)); throw new Error("project: list, create, get, use, settings, delete"); }
async function environment(s: State, action: string | undefined, a: string[]): Promise<void> { const projectId = await resolve(s, "project"); if (action === "list") return void await request(s, "GET", `/projects/${projectId}/environments`); if (action === "create") return void await request(s, "POST", `/projects/${projectId}/environments`, { name: requireArg(a, 0, "environment name"), is_production: Boolean(s.flags.production) }); const id = await resolve(s, "environment", a[0]); if (action === "use") { s.context.environment = id; delete s.context.service; await saveConfig(s.context, s.credentials); return void success("Environment selected.", s.out); } if (action === "clone") return void await request(s, "POST", `/environments/${id}/clone`, { name: requireArg(a, 1, "clone name") }); if (action === "delete") { await confirm(s, `Destroy environment ${id}?`); return void await request(s, "DELETE", `/environments/${id}`); } if (action === "get") return void await request(s, "GET", `/environments/${id}`); if (action === "settings") return void await request(s, "PATCH", `/environments/${id}`, jsonBody(s.flags)); throw new Error("env: list, create, get, use, clone, settings, delete"); }
async function service(s: State, action: string | undefined, a: string[]): Promise<void> { const env = await resolve(s, "environment"); if (action === "list") return void await request(s, "GET", `/environments/${env}/services`); if (action === "graph") { const services = await s.api.request("GET", `/environments/${env}/services`) as Array<{ id: string; name: string; source_repo: string | null; build_config: Record<string, unknown> }> ; const graph = serviceGraph(services); return void (s.out.json ? print(graph, s.out) : console.log(formatServiceGraph(graph))); } if (action === "create") return void await request(s, "POST", `/environments/${env}/services`, jsonBody(s.flags) ?? { name: requireArg(a, 0, "service name"), source_repo: stringFlag(s.flags, "repo"), source_branch: stringFlag(s.flags, "branch") ?? "main", container_port: Number(stringFlag(s.flags, "port") ?? 8080) }); if (action === "template") return void await request(s, "POST", `/environments/${env}/database-templates/${requireArg(a, 0, "template")}`); const id = await resolve(s, "service", a[0]); if (action === "use") { s.context.service = id; await saveConfig(s.context, s.credentials); return void success("Service selected.", s.out); } if (action === "get") return void await request(s, "GET", `/services/${id}`); if (action === "settings") return void await request(s, "PATCH", `/services/${id}`, jsonBody(s.flags)); if (action === "delete") { await confirm(s, `Delete service ${id}?`); return void await request(s, "DELETE", `/services/${id}${s.flags["delete-volume"] ? "?confirm_volume_deletion=true" : ""}`); } throw new Error("service: list, graph, create, template, get, use, settings, delete"); }
async function variable(s: State, action: string | undefined, a: string[]): Promise<void> { const id = await resolve(s, "service", stringFlag(s.flags, "service")); if (action === "list") return void await request(s, "GET", `/services/${id}/variables`); const key = requireArg(a, 0, "variable key"); if (action === "set") { const value = a.slice(1).join(" ") || stringFlag(s.flags, "value"); if (!value) throw new Error("Variable value is required."); return void await request(s, "PUT", `/services/${id}/variables/${encodeURIComponent(key)}`, { value }); } if (action === "unset") { await confirm(s, `Unset ${key}?`); return void await request(s, "DELETE", `/services/${id}/variables/${encodeURIComponent(key)}`); } throw new Error("var: list, set KEY VALUE, unset KEY"); }
async function operation(s: State, action: string | undefined, a: string[]): Promise<void> { const id = await resolve(s, "service", a[0]); if (action === "list") return void await request(s, "GET", `/services/${id}/operations?format=envelope`); if (action === "update") return void await request(s, "PATCH", `/services/${id}/operations`, jsonBody(s.flags)); const kind = requireArg([action ?? ""], 0, "operation kind"); const result = await s.api.request("POST", `/services/${id}/operations/${kind}`, jsonBody(s.flags), { "idempotency-key": stringFlag(s.flags, "idempotency-key") ?? crypto.randomUUID() }); print(result, s.out); }
async function githubImport(s: State, action: string | undefined, a: string[]): Promise<void> { const routes: Record<string, string> = { status: "/github/import/status", templates: "/github/import/templates", installations: "/github/import/installations" }; if (action && routes[action]) return void await request(s, "GET", routes[action]); if (action === "repositories") return void await request(s, "GET", `/github/import/repositories?installation_id=${encodeURIComponent(requireArg(a, 0, "installation id"))}`); if (action === "branches") return void await request(s, "GET", `/github/import/branches?installation_id=${encodeURIComponent(requireArg(a, 0, "installation id"))}&repository=${encodeURIComponent(requireArg(a, 1, "repository"))}`); if (action === "preview") return void await request(s, "POST", "/github/import/preview", jsonBody(s.flags)); if (action === "create") { await confirm(s, "Create project and deploy imported repository?"); return void await request(s, "POST", "/github/imports", jsonBody(s.flags)); } if (action === "get") return void await request(s, "GET", `/github/imports/${requireArg(a, 0, "import id")}`); throw new Error("import: status, templates, installations, repositories, branches, preview, create, get"); }
async function domain(s: State, action: string | undefined, a: string[]): Promise<void> { const env = await resolve(s, "environment"); if (action === "list") return void await request(s, "GET", `/environments/${env}/domains`); if (action === "create") return void await request(s, "POST", `/environments/${env}/domains`, jsonBody(s.flags)); if (action === "delete") { await confirm(s, `Delete domain ${requireArg(a, 0, "domain id")}?`); return void await request(s, "DELETE", `/domains/${a[0]}`); } if (action === "settings") return void await request(s, "PATCH", `/domains/${requireArg(a, 0, "domain id")}`, jsonBody(s.flags)); throw new Error("domain: list, create, settings, delete"); }
async function advisor(s: State, action: string | undefined): Promise<void> { if (action === "diagnose") { const result = await advisorRequest(s.api, "diagnose", undefined, jsonBody(s.flags)); if (s.out.json) return void print(result, s.out); console.log("Model-generated diagnosis (may be incomplete):"); return void print(result, s.out); } if (action === "scan" || action === "accept") { const environment = await resolve(s, "environment"); const body = action === "scan" ? { repository_path: stringFlag(s.flags, "path") ?? requireArg([], 0, "--path") } : jsonBody(s.flags); if (!body) throw new Error("advisor accept requires exactly one proposal in --data JSON."); return void print(await advisorRequest(s.api, action, environment, body), s.out); } throw new Error("advisor: scan --path PATH, accept --data JSON, diagnose --data JSON"); }

async function main(): Promise<void> { const parsed = parse(process.argv.slice(2)); const saved = await loadConfig(); const context = mergeContext(saved.context, { project: stringFlag(parsed.flags, "project"), environment: stringFlag(parsed.flags, "env"), service: stringFlag(parsed.flags, "service") }); const url = stringFlag(parsed.flags, "url") ?? process.env.RUDDER_URL ?? saved.credentials.url ?? "http://localhost:8000"; const state: State = { api: new ApiClient(url, process.env.RUDDER_TOKEN ?? saved.credentials.token), context, credentials: { ...saved.credentials, url }, flags: parsed.flags, out: { json: Boolean(parsed.flags.json) } }; const noun = parsed.args[0]; const launch = !noun && Boolean(process.stdin.isTTY) && !parsed.flags.json && !parsed.flags["no-interactive"];
  if (launch) {
    await requireAuthentication(state);
    await runLauncher({ actions: {
      chooseTarget: () => chooseProjectEnvironment(state),
      deploy: () => command(state, ["deploy"]),
      status: () => command(state, ["status"]),
      logs: () => command(state, ["logs"]),
      services: () => command(state, ["service", "list"]),
      variables: () => command(state, ["var", "list"]),
      advisor: () => command(state, ["advisor", "diagnose"]),
      signOut: () => command(state, ["logout"]),
    } });
    return;
  }
  if (![undefined, "help", "--help", "login", "logout"].includes(noun)) await requireAuthentication(state); await command(state, parsed.args); }
main().catch((error: unknown) => { fail(error instanceof ApiError || error instanceof Error ? error.message : String(error)); process.exitCode = error instanceof ApiError && error.status === 401 ? 1 : 1; });
