import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type Context = { project?: string; environment?: string; service?: string };
export type Credentials = { url?: string; token?: string };
const configPath = process.env.RUDDER_CONFIG ?? join(homedir(), ".config", "rudder", "config.json");

export function contextFrom(json: string): Context {
  try { const data: unknown = JSON.parse(json); return typeof data === "object" && data !== null ? pick(data as Record<string, unknown>) : {}; } catch { return {}; }
}
export function mergeContext(saved: Context, explicit: Context): Context { return { ...saved, ...Object.fromEntries(Object.entries(explicit).filter(([, v]) => v !== undefined)) }; }
export async function loadConfig(): Promise<{ context: Context; credentials: Credentials }> {
  try { const raw = JSON.parse(await readFile(configPath, "utf8")) as Record<string, unknown>; return { context: pick((raw.context ?? {}) as Record<string, unknown>), credentials: pickCredentials((raw.credentials ?? {}) as Record<string, unknown>) }; } catch { return { context: {}, credentials: {} }; }
}
export async function saveConfig(context: Context, credentials: Credentials): Promise<void> { await mkdir(dirname(configPath), { recursive: true, mode: 0o700 }); await writeFile(configPath, JSON.stringify({ context, credentials }, null, 2) + "\n", { mode: 0o600 }); }
function pick(data: Record<string, unknown>): Context { return Object.fromEntries(["project", "environment", "service"].flatMap(k => typeof data[k] === "string" ? [[k, data[k]]] : [])); }
function pickCredentials(data: Record<string, unknown>): Credentials { return Object.fromEntries(["url", "token"].flatMap(k => typeof data[k] === "string" ? [[k, data[k]]] : [])); }
