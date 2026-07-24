/**
 * The whole app when there is no session. Not a route — there is exactly one
 * screen behind the gate and no reason for a URL that renders it.
 *
 * There is no signup (Phase 1 step 3: the single user is seeded from `.env`)
 * and no "remember me": the cookie's own `Max-Age` is the session length.
 */
export function LoginScreen() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-surface">
      <main className="w-80 rounded-md border border-hairline bg-surface-raised p-xl shadow-elev-2">
        <div className="flex items-center gap-sm">
          <span className="h-2 w-2 rounded-full bg-accent" aria-hidden />
          <h1 className="text-heading-md text-ink">rudder</h1>
        </div>
        <p className="pt-xs text-micro text-ink-faint">Continue with GitHub to access Rudder.</p>
        <a
          href="/api/auth/github/start"
          className="mt-lg w-full rounded-sm bg-accent px-lg py-sm text-button font-medium text-on-accent transition-colors hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-50"
        >
          Continue with GitHub
        </a>
      </main>
    </div>
  );
}
