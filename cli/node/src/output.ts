export type Output = { json: boolean; quiet?: boolean };
export function print(value: unknown, out: Output): void { if (out.json) console.log(JSON.stringify(value)); else if (typeof value === "string") console.log(value); else console.log(JSON.stringify(value, null, 2)); }
export function success(message: string, out: Output): void { if (!out.json && !out.quiet) console.log(`\u001b[32m✓\u001b[0m ${message}`); }
export function fail(message: string): void { console.error(`\u001b[31merror:\u001b[0m ${message}`); }
