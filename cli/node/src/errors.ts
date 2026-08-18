/** Errors whose exit status is part of the CLI's public automation contract. */
export class CliUsageError extends Error {}

export class CliCancellationError extends Error {
  constructor() { super("Operation cancelled."); }
}

/** A JSON stream already emitted records, so its error must not be rendered again at top level. */
export class CliStreamOutputError extends Error {
  constructor(readonly cause: unknown) {
    super(cause instanceof Error ? cause.message : String(cause));
  }
}
