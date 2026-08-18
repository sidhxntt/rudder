import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(process.cwd(), "lib/queries.ts"), "utf8");

describe("shared-client refresh policy", () => {
  it.each(["useEnvironments", "useServices", "useDomains", "useVariables"])(
    "%s refreshes state changed by another Rudder client",
    (hook) => {
      const section = source.slice(source.indexOf(`export function ${hook}`), source.indexOf("\nexport function", source.indexOf(`export function ${hook}`) + 1));
      expect(section).toContain("refetchInterval: LIVE_POLL_MS");
    },
  );
});
