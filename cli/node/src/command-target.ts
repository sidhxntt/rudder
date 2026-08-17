/**
 * The parser reserves the second token as an action for resource commands
 * (`project list`, `service create`). Commands such as `deploy SERVICE_ID`
 * have no action, so their target occupies that same token.
 */
export function commandTarget(action: string | undefined, rest: string[]): string | undefined {
  return rest[0] ?? action;
}
