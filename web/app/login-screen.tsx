/**
 * The whole app when there is no session. Not a route — there is exactly one
 * screen behind the gate and no reason for a URL that renders it.
 *
 * There is no signup (Phase 1 step 3: the single user is seeded from `.env`)
 * and no "remember me": the cookie's own `Max-Age` is the session length.
 */
function GitHubMark() {
  return (
    <svg
      aria-hidden="true"
      className="h-5 w-5 shrink-0"
      fill="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        clipRule="evenodd"
        fillRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.009-.868-.014-1.703-2.782.605-3.369-1.342-3.369-1.342-.455-1.157-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.071 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.091-.647.349-1.088.635-1.339-2.221-.253-4.556-1.113-4.556-4.951 0-1.093.39-1.987 1.03-2.687-.103-.253-.447-1.271.098-2.65 0 0 .84-.27 2.75 1.027A9.564 9.564 0 0 1 12 6.336a9.59 9.59 0 0 1 2.504.337c1.909-1.297 2.748-1.027 2.748-1.027.546 1.379.202 2.397.1 2.65.64.7 1.028 1.594 1.028 2.687 0 3.848-2.339 4.695-4.568 4.943.359.31.678.921.678 1.856 0 1.339-.012 2.419-.012 2.747 0 .269.18.58.688.481A10.02 10.02 0 0 0 22 12.017C22 6.484 17.523 2 12 2Z"
      />
    </svg>
  );
}

export function LoginScreen() {
  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-surface px-lg py-2xl">
      <main className="w-full max-w-sm rounded-lg border border-hairline bg-surface-raised p-xl shadow-elev-2 sm:p-2xl">
        <header className="border-b border-hairline pb-xl">
          <div className="flex items-center gap-md">
            <span
              className="flex h-9 w-9 items-center justify-center rounded-md border border-hairline bg-surface"
              aria-hidden
            >
              <span className="h-2 w-2 rounded-full bg-accent" />
            </span>
            <div>
              <p className="text-heading-md text-ink">rudder</p>
              <p className="pt-2xs text-micro text-ink-faint">Deployment workspace</p>
            </div>
          </div>
        </header>

        <section className="pt-xl">
          <h1 className="text-heading-md text-ink">Sign in to your workspace</h1>
          <p className="pt-xs text-body-sm text-ink-faint">
            Connect GitHub to access your repositories and deploy services.
          </p>

          <a
            href="/api/auth/github/start"
            className="mt-xl flex w-full items-center justify-center gap-sm rounded-sm bg-accent px-lg py-md text-button font-medium text-on-accent transition-colors hover:bg-accent-deep"
          >
            <GitHubMark />
            Continue with GitHub
          </a>

          <p className="pt-md text-micro leading-relaxed text-ink-faint">
            You will authorize Rudder through GitHub.
          </p>
        </section>
      </main>
    </div>
  );
}
