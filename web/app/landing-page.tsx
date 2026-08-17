import Link from "next/link";

type LandingPageProps = {
  authenticated: boolean;
};

function RudderMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 font-medium tracking-[-0.03em] text-ink">
      <span className="relative flex h-7 w-7 items-center justify-center rounded-md border border-accent/60 bg-accent/10" aria-hidden>
        <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_16px_rgba(62,207,142,0.8)]" />
      </span>
      {!compact ? <span>rudder</span> : null}
    </span>
  );
}

function ArrowRight() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16">
      <path d="M3 8h9M8.5 3.5 13 8l-4.5 4.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

function GitHubMark() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.009-.868-.014-1.703-2.782.605-3.369-1.342-3.369-1.342-.455-1.157-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.071 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.091-.647.349-1.088.635-1.339-2.221-.253-4.556-1.113-4.556-4.951 0-1.093.39-1.987 1.03-2.687-.103-.253-.447-1.271.098-2.65 0 0 .84-.27 2.75 1.027A9.564 9.564 0 0 1 12 6.336a9.59 9.59 0 0 1 2.504.337c1.909-1.297 2.748-1.027 2.748-1.027.546 1.379.202 1.397.1 2.65.64.7 1.028 1.594 1.028 2.687 0 3.848-2.339 4.695-4.568 4.943.359.31.678.921.678 1.856 0 1.339-.012 2.419-.012 2.747 0 .269.18.58.688.481A10.02 10.02 0 0 0 22 12.017C22 6.484 17.523 2 12 2Z" />
    </svg>
  );
}

function DeploymentDiagram() {
  return (
    <div className="relative isolate grid overflow-hidden border border-hairline bg-[#141916] shadow-[0_28px_90px_rgba(0,0,0,0.42)] sm:grid-cols-[42px_minmax(0,1fr)]">
      <div className="relative hidden border-r border-hairline bg-surface-inset sm:block">
        <span className="absolute left-1/2 top-6 -translate-x-1/2 [writing-mode:vertical-rl] font-mono text-micro uppercase tracking-[0.18em] text-ink-faint">release topology</span>
        <span className="absolute bottom-5 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-accent shadow-[0_0_16px_rgba(62,207,142,0.8)]" />
      </div>
      <div className="relative min-w-0 p-4 sm:p-6">
        <div className="absolute inset-0 opacity-40 [background-image:radial-gradient(circle_at_1px_1px,rgba(178,178,178,0.22)_1px,transparent_0)] [background-size:22px_22px]" />
        <div className="relative flex items-center justify-between border-b border-hairline pb-4 text-[11px] uppercase tracking-[0.12em] text-ink-faint">
          <span>release / 106b06e</span>
          <span className="flex items-center gap-1.5 text-accent"><span className="h-1.5 w-1.5 rounded-full bg-accent" /> live</span>
        </div>
        <svg className="relative mt-4 h-[300px] w-full sm:h-[365px]" viewBox="0 0 540 320" role="img" aria-label="A Rudder release connects an application to PostgreSQL and Redis">
        <defs>
          <linearGradient id="edge" x1="0" x2="1">
            <stop stopColor="#3ecf8e" stopOpacity="0.15" />
            <stop offset="0.48" stopColor="#3ecf8e" stopOpacity="0.9" />
            <stop offset="1" stopColor="#3ecf8e" stopOpacity="0.15" />
          </linearGradient>
          <filter id="glow"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        <path d="M260 160 C 325 160, 315 88, 385 88 M260 160 C325 160,315 242,385 242" stroke="url(#edge)" strokeWidth="2" fill="none" />
        <path d="M140 160 C 170 160,185 160,220 160" stroke="#3ecf8e" strokeOpacity="0.7" strokeWidth="2" fill="none" filter="url(#glow)" />
        <rect x="26" y="121" width="114" height="78" rx="9" fill="#202824" stroke="#3ecf8e" strokeOpacity="0.75" />
        <text x="43" y="149" fill="#ededed" fontSize="13" fontFamily="ui-sans-serif, system-ui">GitHub</text>
        <text x="43" y="174" fill="#3ecf8e" fontSize="10" fontFamily="ui-monospace, monospace">commit pushed</text>
        <circle cx="118" cy="145" r="4" fill="#3ecf8e" />
        <rect x="220" y="115" width="118" height="90" rx="9" fill="#26342d" stroke="#3ecf8e" />
        <text x="238" y="146" fill="#ededed" fontSize="14" fontFamily="ui-sans-serif, system-ui">application</text>
        <text x="238" y="172" fill="#a7f3d0" fontSize="10" fontFamily="ui-monospace, monospace">ready / 3000</text>
        <circle cx="316" cy="140" r="4" fill="#3ecf8e" />
        <rect x="384" y="48" width="124" height="78" rx="9" fill="#202020" stroke="#3a3a3a" />
        <text x="403" y="78" fill="#ededed" fontSize="13" fontFamily="ui-sans-serif, system-ui">postgres</text>
        <text x="403" y="101" fill="#9a9a9a" fontSize="10" fontFamily="ui-monospace, monospace">private / 5432</text>
        <circle cx="486" cy="74" r="4" fill="#3ecf8e" />
        <rect x="384" y="204" width="124" height="78" rx="9" fill="#202020" stroke="#3a3a3a" />
        <text x="403" y="234" fill="#ededed" fontSize="13" fontFamily="ui-sans-serif, system-ui">redis</text>
        <text x="403" y="257" fill="#9a9a9a" fontSize="10" fontFamily="ui-monospace, monospace">private / 6379</text>
        <circle cx="486" cy="230" r="4" fill="#3ecf8e" />
        <text x="153" y="147" fill="#707070" fontSize="9" fontFamily="ui-monospace, monospace">build</text>
        <text x="337" y="119" fill="#707070" fontSize="9" fontFamily="ui-monospace, monospace">uses database</text>
        <text x="337" y="220" fill="#707070" fontSize="9" fontFamily="ui-monospace, monospace">uses cache</text>
        </svg>
        <div className="relative mt-2 flex items-center justify-between border border-hairline bg-surface-inset px-3 py-2 font-mono text-[11px] text-ink-mute">
          <span><span className="text-accent">[LIVE]</span> public route promoted</span>
          <span className="text-ink-faint">00:42</span>
        </div>
      </div>
    </div>
  );
}

const deliveryLoop = [
  ["01", "Repository event", "A GitHub push starts with the branch and source you chose."],
  ["02", "Resolved service graph", "Rudder reads the application alongside its Compose-defined private dependencies."],
  ["03", "Release record", "A live deployment keeps its build, runtime state, and restore point in view."],
];

const features = [
  ["Your service graph, made visible", "Import a Compose repository and see the application, database, cache, and worker relationships before you deploy."],
  ["A release you can inspect", "Follow build and runtime logs, see actual service state, and keep immutable deployment records for restore."],
  ["Environments without a second system", "Clone an isolated service graph for production or let GitHub pull requests create capped preview environments."],
  ["Frontends included", "Deploy Vite, CRA, Astro, and Next static export projects with permanent release URLs; run Next SSR as an app container."],
  ["Rudder AI, grounded in your workspace", "Ask a read-only assistant about the current environment, releases, services, runtime signals, and Rudder documentation. It explains; it never changes state."],
  ["Rudder Advisor, before you deploy", "Scan a local checkout for an app, worker, database, cache, and wiring suggestions. Nothing is applied automatically: review each ghost proposal before accepting it."],
];

export function LandingPage({ authenticated }: LandingPageProps) {
  const deployHref = authenticated ? "/dashboard?import=github" : "/api/auth/github/start";

  return (
    <main className="min-h-screen overflow-x-hidden bg-surface text-ink selection:bg-accent selection:text-on-accent">
      <nav aria-label="Public navigation" className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <div className="flex items-center gap-3">
          <RudderMark />
          <span className="rounded-xs border border-hairline-strong bg-surface-raised px-2 py-1 text-micro font-medium text-ink-mute">
            In development
          </span>
        </div>
        <div className="flex items-center gap-3 text-caption">
          <a href="#capabilities" className="hidden text-ink-mute transition-colors hover:text-ink sm:inline">Capabilities</a>
          <a href="#run-locally" className="hidden text-ink-mute transition-colors hover:text-ink sm:inline">Run locally</a>
          {authenticated ? <Link href="/dashboard" className="rounded-sm border border-hairline-strong px-3 py-2 text-ink-secondary transition-colors hover:border-accent hover:text-ink">Open workspace</Link> : null}
        </div>
      </nav>

      <section className="relative mx-auto grid max-w-[1440px] gap-12 border-y border-hairline px-5 py-14 sm:px-8 sm:py-20 lg:grid-cols-[minmax(0,0.88fr)_minmax(520px,1.12fr)] lg:px-10 lg:py-24">
        <div className="relative z-10 flex max-w-2xl flex-col justify-between lg:py-4">
          <div>
            <h1 className="max-w-xl text-[clamp(3.5rem,7vw,6.1rem)] font-medium leading-[0.92] tracking-[-0.04em] text-ink">
              Your deployment should leave a trail.
            </h1>
            <p className="mt-7 max-w-lg text-lg leading-8 text-ink-secondary">
              Rudder turns the repository you already trust into a release you can inspect: its application, private services, runtime state, and route to recovery.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link href={deployHref} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-sm bg-accent px-5 text-button font-medium text-on-accent transition-transform duration-200 hover:-translate-y-0.5 hover:bg-accent-deep">
                <GitHubMark /> {authenticated ? "Deploy from GitHub" : "Sign in with GitHub"} <ArrowRight />
              </Link>
              <a href="#run-locally" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-sm border border-hairline-strong px-5 text-button text-ink-secondary transition-colors hover:border-accent hover:text-ink">
                Run locally
              </a>
            </div>
            <p className="mt-4 text-caption text-ink-faint">Single-tenant by design. GitHub is the sign-in and repository boundary.</p>
          </div>
          <dl className="mt-12 grid max-w-lg grid-cols-2 border-t border-hairline pt-5 text-caption sm:mt-16">
            <div><dt className="font-mono text-micro uppercase tracking-[0.14em] text-ink-faint">Control</dt><dd className="mt-2 text-ink-secondary">Your runtime boundary</dd></div>
            <div className="border-l border-hairline pl-5"><dt className="font-mono text-micro uppercase tracking-[0.14em] text-ink-faint">Evidence</dt><dd className="mt-2 text-ink-secondary">Logs, state, restore</dd></div>
          </dl>
        </div>
        <div className="lg:-mr-10"><DeploymentDiagram /></div>
      </section>

      <section aria-labelledby="delivery-loop-title" className="border-b border-hairline bg-surface-inset">
        <div className="mx-auto grid max-w-[1440px] gap-10 px-5 py-14 sm:px-8 lg:grid-cols-[0.64fr_1.36fr] lg:px-10 lg:py-16">
          <div>
            <h2 id="delivery-loop-title" className="max-w-sm text-[clamp(2.2rem,4.2vw,4.5rem)] font-medium leading-[0.96] tracking-[-0.04em] text-ink">The delivery loop, in plain sight.</h2>
          </div>
          <ol className="grid border-t border-hairline sm:grid-cols-3 sm:border-l">
            {deliveryLoop.map(([number, title, copy]) => (
              <li key={title} className="border-b border-hairline py-5 sm:border-b-0 sm:border-r sm:px-6 sm:py-2 first:sm:pt-2 last:sm:border-r-0">
                <span className="font-mono text-[11px] text-accent">{number}</span>
                <h3 className="mt-8 text-heading-md text-ink">{title}</h3>
                <p className="mt-3 max-w-xs text-caption leading-6 text-ink-mute">{copy}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="capabilities" className="mx-auto max-w-7xl px-5 py-24 sm:px-8 sm:py-32 lg:px-10">
        <div className="grid gap-10 lg:grid-cols-[0.86fr_1.14fr] lg:items-end">
          <h2 className="max-w-xl text-[clamp(2.7rem,5vw,5.4rem)] font-medium leading-[0.94] tracking-[-0.04em] text-ink">Deploy the code. Keep the context.</h2>
          <p className="max-w-xl text-lg leading-8 text-ink-secondary">Rudder keeps the mechanics of shipping close to the work: services, configuration, release history, and the evidence behind every state.</p>
        </div>
        <div className="mt-20 grid gap-x-14 gap-y-0 md:grid-cols-2">
          {features.map(([title, copy], index) => (
            <article key={title} className="grid grid-cols-[auto_1fr] gap-5 border-t border-hairline-strong py-7">
              <span className="font-mono text-xs text-accent">0{index + 1}</span>
              <div><h3 className="text-heading-lg text-ink">{title}</h3><p className="mt-3 max-w-md text-body-sm leading-7 text-ink-mute">{copy}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="border-y border-hairline bg-[#171a18]">
        <div className="mx-auto grid max-w-7xl gap-12 px-5 py-24 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:px-10 lg:py-28">
          <div>
            <h2 className="text-[clamp(2.25rem,4vw,4.2rem)] font-medium leading-[0.98] tracking-[-0.045em] text-ink">Different tools. Different boundary.</h2>
            <p className="mt-5 max-w-md text-body leading-7 text-ink-secondary">Rudder belongs with the developer who wants a fast delivery loop and a visible, self-hosted runtime—not a black box.</p>
          </div>
          <div className="overflow-x-auto border-y border-hairline">
            <table className="w-full min-w-[560px] border-collapse text-left text-caption">
              <thead className="border-b border-hairline text-ink-faint"><tr><th className="py-4 font-normal">Approach</th><th className="py-4 font-normal">Best fit</th><th className="py-4 font-normal">Operating model</th></tr></thead>
              <tbody className="divide-y divide-hairline text-ink-secondary">
                <tr><th className="py-5 font-medium text-ink">Vercel</th><td className="py-5">Managed frontend delivery</td><td className="py-5">Platform-managed deployment experience</td></tr>
                <tr><th className="py-5 font-medium text-ink">Railway</th><td className="py-5">Managed app platform</td><td className="py-5">Platform-managed services and delivery</td></tr>
                <tr><th className="py-5 font-medium text-accent">Rudder</th><td className="py-5">Self-hosted apps and private services</td><td className="py-5">Your service graph, releases, and operator control</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-24 sm:px-8 sm:py-32 lg:px-10">
        <div className="grid gap-14 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <h2 className="text-[clamp(2.25rem,4vw,4.2rem)] font-medium leading-[0.98] tracking-[-0.045em] text-ink">Start where you are.</h2>
            <p className="mt-5 max-w-md text-body leading-7 text-ink-secondary">Build on your laptop with the same product model you use to evaluate a Kubernetes target.</p>
          </div>
          <div className="space-y-4">
            <div className="flex gap-5 border-b border-hairline pb-5"><span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" /><div><h3 className="text-heading-md">Local Docker</h3><p className="mt-2 text-caption leading-6 text-ink-mute">Available for a self-hosted control plane, agent, build runtime, registry, and ingress.</p></div></div>
            <div className="flex gap-5 border-b border-hairline pb-5"><span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" /><div><h3 className="text-heading-md">Kind</h3><p className="mt-2 text-caption leading-6 text-ink-mute">Available locally for the Kubernetes resource model and isolated Compose-derived namespaces.</p></div></div>
            <div className="flex gap-5 border-b border-hairline pb-5"><span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-status-building" /><div><h3 className="text-heading-md">GKE controlled beta</h3><p className="mt-2 text-caption leading-6 text-ink-mute">Verified shared-pool GKE delivery path with private nodes, immutable images, public TLS, and restore evidence.</p></div></div>
            <div className="flex gap-5"><span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-hairline-strong" /><div><h3 className="text-heading-md">AWS/EKS and Azure/AKS</h3><p className="mt-2 text-caption leading-6 text-ink-mute">Planned provider adapters. Not currently available in Rudder.</p></div></div>
          </div>
        </div>
      </section>

      <section id="run-locally" className="border-t border-hairline bg-surface-soft">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-24 sm:px-8 lg:grid-cols-[0.85fr_1.15fr] lg:px-10 lg:py-28">
          <div><h2 className="text-[clamp(2.25rem,4vw,4.2rem)] font-medium leading-[0.98] tracking-[-0.045em] text-ink">Run Rudder locally.</h2><p className="mt-5 max-w-md text-body leading-7 text-ink-secondary">Bring up the stack, migrate the control plane, then connect GitHub from the browser. Full environment guidance stays in the repository.</p><a className="mt-7 inline-flex items-center gap-2 text-caption text-accent hover:text-accent-soft" href="https://github.com/sidhxntt/rudder#setup" target="_blank" rel="noreferrer">Read the setup guide <ArrowRight /></a></div>
          <pre className="overflow-x-auto rounded-lg border border-hairline bg-surface-inset p-5 text-sm leading-7 text-ink-secondary"><code><span className="text-ink-faint"># configure local secrets</span>{"\n"}cp .env.example .env{"\n\n"}<span className="text-ink-faint"># start the local control plane</span>{"\n"}docker compose -f docker-compose.dev.yml up -d{"\n"}docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head{"\n"}docker compose -f docker-compose.dev.yml restart control-plane</code></pre>
        </div>
      </section>

      <footer className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 text-caption text-ink-faint sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10"><RudderMark compact /><div className="flex gap-5"><a className="hover:text-ink" href="https://github.com/sidhxntt/rudder" target="_blank" rel="noreferrer">GitHub</a><a className="hover:text-ink" href="https://github.com/sidhxntt/rudder/tree/main/docs" target="_blank" rel="noreferrer">Documentation</a><Link className="hover:text-ink" href={authenticated ? "/dashboard" : "/api/auth/github/start"}>{authenticated ? "Workspace" : "Sign in"}</Link></div></footer>
    </main>
  );
}
