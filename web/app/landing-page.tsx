import Link from "next/link";

import RudderHero from "@/components/rudder-hero";

type LandingPageProps = {
  authenticated: boolean;
};

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

const platforms = [
  ["Local Docker", "Available for a self-hosted control plane, agent, build runtime, registry, and ingress.", "bg-accent"],
  ["Kind", "Available locally for the Kubernetes resource model and isolated Compose-derived namespaces.", "bg-accent"],
  ["GKE controlled beta", "Verified shared-pool GKE delivery path with private nodes, immutable images, public TLS, and restore evidence.", "bg-status-building"],
  ["AWS/EKS and Azure/AKS", "Planned provider adapters. Not currently available in Rudder.", "bg-paper-line-strong"],
];

/* Keys, in the hero's language: each sits on a hard shadow and goes down when pressed. */
const keyBase =
  "inline-flex min-h-12 items-center justify-center gap-2.5 rounded-[15px] px-6 text-[15px] font-semibold tracking-[-0.01em] transition-[transform,box-shadow] duration-100 ease-out active:translate-y-[3.5px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paper-ink";
const keyPrimary = `${keyBase} bg-accent text-on-accent shadow-[0_4px_0_rgba(0,52,28,.36),0_6px_8px_rgba(0,52,28,.2),inset_0_1px_0_rgba(255,255,255,.35)] active:shadow-[0_.5px_0_rgba(0,52,28,.36),0_1px_2px_rgba(0,52,28,.2)]`;
const keyQuiet = `${keyBase} bg-paper-raised text-paper-ink shadow-[0_4px_0_rgba(29,26,25,.16),0_6px_8px_rgba(29,26,25,.08),inset_0_1px_0_rgba(255,255,255,.9)] active:shadow-[0_.5px_0_rgba(29,26,25,.16),0_1px_2px_rgba(29,26,25,.08)]`;

const sectionTitle = "font-display font-medium leading-[1.04] tracking-[-0.022em] text-paper-ink";

export function LandingPage({ authenticated }: LandingPageProps) {
  const deployHref = authenticated ? "/dashboard?import=github" : "/api/auth/github/start";

  return (
    <div className="min-h-screen overflow-x-hidden bg-paper font-display tracking-[0.004em] text-paper-ink selection:bg-accent selection:text-on-accent">
      <RudderHero
        actions={[
          { label: "Run locally", href: "#run-locally", kind: "quiet" },
          authenticated
            ? { label: "Open workspace", href: "/dashboard", kind: "primary" }
            : { label: "Sign in with GitHub", href: "/api/auth/github/start", kind: "primary", github: true },
        ]}
      />

      <section aria-label="Get started" className="border-y border-paper-line bg-paper-raised">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-20 sm:px-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end lg:gap-20 lg:px-10 lg:py-28">
          <div>
            <p className="max-w-2xl text-[clamp(1.4rem,2.3vw,2rem)] font-medium leading-[1.32] tracking-[-0.012em] text-paper-ink">
              Rudder turns the repository you already trust into a release you can inspect: its application, private services, runtime state, and route to recovery.
            </p>
          </div>
          <div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Link href={deployHref} className={keyPrimary}>
                <GitHubMark /> {authenticated ? "Deploy from GitHub" : "Sign in with GitHub"} <ArrowRight />
              </Link>
              <a href="#run-locally" className={keyQuiet}>
                Run locally
              </a>
            </div>
            <p className="mt-7 text-[14px] leading-6 text-paper-mute">Single-tenant by design. GitHub is the sign-in and repository boundary.</p>
            <dl className="mt-10 grid grid-cols-2 border-t border-paper-line pt-6 text-[14px]">
              <div><dt className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper-faint">Control</dt><dd className="mt-2 text-paper-secondary">Your runtime boundary</dd></div>
              <div className="border-l border-paper-line pl-6"><dt className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper-faint">Evidence</dt><dd className="mt-2 text-paper-secondary">Logs, state, restore</dd></div>
            </dl>
          </div>
        </div>
      </section>

      <section id="delivery-loop" aria-labelledby="delivery-loop-title" className="border-b border-paper-line">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.62fr_1.38fr] lg:gap-16 lg:px-10 lg:py-32">
          <h2 id="delivery-loop-title" className={`${sectionTitle} max-w-sm text-[clamp(2.2rem,3.8vw,3.8rem)]`}>The delivery loop, in plain sight.</h2>
          <ol className="grid border-t border-paper-line sm:grid-cols-3 sm:border-l">
            {deliveryLoop.map(([number, title, copy]) => (
              <li key={title} className="border-b border-paper-line py-7 sm:border-b-0 sm:border-r sm:px-8 sm:py-4 last:sm:border-r-0">
                <span className="font-mono text-[11px] text-accent-ink">{number}</span>
                <h3 className="mt-12 text-[19px] leading-snug tracking-[-0.01em] text-paper-ink">{title}</h3>
                <p className="mt-4 max-w-xs text-[15px] leading-7 text-paper-mute">{copy}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="capabilities" className="mx-auto max-w-7xl px-5 py-28 sm:px-8 sm:py-36 lg:px-10">
        <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end lg:gap-20">
          <h2 className={`${sectionTitle} max-w-xl text-[clamp(2.6rem,4.4vw,4.6rem)]`}>Deploy the code. Keep the context.</h2>
          <p className="max-w-xl text-lg leading-8 text-paper-secondary">Rudder keeps the mechanics of shipping close to the work: services, configuration, release history, and the evidence behind every state.</p>
        </div>
        <div className="mt-24 grid gap-x-20 md:grid-cols-2">
          {features.map(([title, copy], index) => (
            <article key={title} className="grid grid-cols-[auto_1fr] gap-6 border-t border-paper-line-strong py-10">
              <span className="font-mono text-xs text-accent-ink">0{index + 1}</span>
              <div>
                <h3 className="text-[21px] leading-snug tracking-[-0.012em] text-paper-ink">{title}</h3>
                <p className="mt-4 max-w-md text-[15px] leading-7 text-paper-mute">{copy}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section id="compare" className="border-y border-paper-line bg-paper-sunk">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-28 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20 lg:px-10 lg:py-36">
          <div>
            <h2 className={`${sectionTitle} text-[clamp(2.25rem,4vw,4.2rem)]`}>Different tools. Different boundary.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-paper-secondary">Rudder belongs with the developer who wants a fast delivery loop and a visible, self-hosted runtime—not a black box.</p>
          </div>
          <div className="overflow-x-auto border-y border-paper-line-strong">
            <table className="w-full min-w-[560px] border-collapse text-left text-[15px]">
              <thead className="border-b border-paper-line-strong text-paper-faint"><tr><th className="py-4 font-normal">Approach</th><th className="py-4 font-normal">Best fit</th><th className="py-4 font-normal">Operating model</th></tr></thead>
              <tbody className="divide-y divide-paper-line-strong text-paper-secondary">
                <tr><th className="py-5 font-medium text-paper-ink">Vercel</th><td className="py-5">Managed frontend delivery</td><td className="py-5">Platform-managed deployment experience</td></tr>
                <tr><th className="py-5 font-medium text-paper-ink">Railway</th><td className="py-5">Managed app platform</td><td className="py-5">Platform-managed services and delivery</td></tr>
                <tr><th className="py-5 font-semibold text-accent-ink">Rudder</th><td className="py-5">Self-hosted apps and private services</td><td className="py-5">Your service graph, releases, and operator control</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="platforms" className="mx-auto max-w-7xl px-5 py-28 sm:px-8 sm:py-36 lg:px-10">
        <div className="grid gap-14 lg:grid-cols-[0.85fr_1.15fr] lg:gap-20">
          <div>
            <h2 className={`${sectionTitle} text-[clamp(2.25rem,4vw,4.2rem)]`}>Start where you are.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-paper-secondary">Build on your laptop with the same product model you use to evaluate a Kubernetes target.</p>
          </div>
          <ul className="space-y-6">
            {platforms.map(([name, copy, dot], i) => (
              <li key={name} className={`flex gap-5 pb-6 ${i < platforms.length - 1 ? "border-b border-paper-line" : ""}`}>
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-black/10 ${dot}`} aria-hidden />
                <div>
                  <h3 className="text-[19px] leading-snug tracking-[-0.01em] text-paper-ink">{name}</h3>
                  <p className="mt-2 text-[15px] leading-7 text-paper-mute">{copy}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section id="run-locally" className="border-t border-paper-line bg-paper-raised">
        <div className="mx-auto grid max-w-7xl gap-12 px-5 py-28 sm:px-8 lg:grid-cols-[0.85fr_1.15fr] lg:gap-20 lg:px-10 lg:py-36">
          <div>
            <h2 className={`${sectionTitle} text-[clamp(2.25rem,4vw,4.2rem)]`}>Run Rudder locally.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-paper-secondary">Bring up the stack, migrate the control plane, then connect GitHub from the browser. Full environment guidance stays in the repository.</p>
            <a className="mt-7 inline-flex items-center gap-2 text-[14px] font-semibold text-accent-ink underline-offset-4 hover:underline" href="https://github.com/sidhxntt/rudder#setup" target="_blank" rel="noreferrer">
              Read the setup guide <ArrowRight />
            </a>
          </div>
          <pre className="overflow-x-auto rounded-[22px] bg-surface-inset p-7 font-mono text-sm leading-8 text-ink-secondary shadow-[0_18px_40px_-18px_rgba(29,26,25,.5)]"><code><span className="text-ink-faint"># configure local secrets</span>{"\n"}cp .env.example .env{"\n\n"}<span className="text-ink-faint"># start the local control plane</span>{"\n"}docker compose -f docker-compose.dev.yml up -d{"\n"}docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head{"\n"}docker compose -f docker-compose.dev.yml restart control-plane</code></pre>
        </div>
      </section>

      <footer className="border-t border-paper-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 text-[13px] text-paper-mute sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
          <span className="text-[17px] font-bold tracking-[-0.045em] text-paper-ink">rudder</span>
          <div className="flex gap-5">
            <a className="hover:text-paper-ink" href="https://github.com/sidhxntt/rudder" target="_blank" rel="noreferrer">GitHub</a>
            <a className="hover:text-paper-ink" href="https://github.com/sidhxntt/rudder/tree/main/docs" target="_blank" rel="noreferrer">Documentation</a>
            <Link className="hover:text-paper-ink" href={authenticated ? "/dashboard" : "/api/auth/github/start"}>{authenticated ? "Workspace" : "Sign in"}</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
