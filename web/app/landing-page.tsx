import Link from "next/link";

import RudderHero from "@/components/rudder-hero";

type LandingPageProps = {
  authenticated: boolean;
};

/* The closing scene reuses the hero's photograph, so the page ends where it began. */
const HILLS = "/design/websites/tessel/hills.webp";

function ArrowRight() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16">
      <path d="M3 8h9M8.5 3.5 13 8l-4.5 4.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
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
  ["Local Docker", "Available for a self-hosted control plane, agent, build runtime, registry, and ingress.", "Available", "bg-accent"],
  ["Kind", "Available locally for the Kubernetes resource model and isolated Compose-derived namespaces.", "Available", "bg-accent"],
  ["GKE controlled beta", "Verified shared-pool GKE delivery path with private nodes, immutable images, public TLS, and restore evidence.", "Beta", "bg-status-building"],
  ["AWS/EKS and Azure/AKS", "Planned provider adapters. Not currently available in Rudder.", "Planned", "bg-petal-line"],
];

/* Section headlines share the hero's face: Fraunces 300 at its display size, upright. */
const serif = "font-serif font-light [font-variation-settings:'opsz'_144] tracking-[-0.025em] leading-[1.04]";

export function LandingPage({ authenticated }: LandingPageProps) {
  const deployHref = authenticated ? "/dashboard?import=github" : "/api/auth/github/start";

  return (
    <div className="min-h-screen overflow-x-hidden bg-dusk font-display tracking-[0.004em] text-dusk-ink selection:bg-accent selection:text-on-accent">
      <RudderHero
        cta={{ label: authenticated ? "Deploy from GitHub" : "Sign in with GitHub", href: deployHref }}
        signIn={authenticated ? { label: "Open workspace", href: "/dashboard" } : { label: "Sign in", href: "/api/auth/github/start" }}
      />

      {/* 1 · the loop, as a path a release travels (dusk, continuing the hero's floor) */}
      <section id="delivery-loop" aria-labelledby="delivery-loop-title" className="bg-dusk">
        <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8 lg:px-10 lg:py-36">
          <h2 id="delivery-loop-title" className={`${serif} max-w-2xl text-[clamp(2.6rem,5vw,4.6rem)] text-dusk-ink`}>
            The delivery loop, in plain sight.
          </h2>
          <ol className="relative mt-20 grid gap-12 md:grid-cols-3 md:gap-10">
            <span aria-hidden className="absolute left-[7px] top-2 bottom-2 w-px bg-gradient-to-b from-accent via-dusk-line-strong to-transparent md:left-0 md:right-0 md:top-[7px] md:bottom-auto md:h-px md:w-auto md:bg-gradient-to-r" />
            {deliveryLoop.map(([number, title, copy]) => (
              <li key={title} className="relative pl-10 md:pl-0 md:pt-12">
                <span aria-hidden className="absolute left-0 top-0 grid h-[15px] w-[15px] place-items-center rounded-full bg-dusk ring-1 ring-accent/60">
                  <span className="h-[5px] w-[5px] rounded-full bg-accent" />
                </span>
                <span className="font-mono text-[12px] text-dusk-faint">{number}</span>
                <h3 className="mt-3 text-[21px] font-medium tracking-[-0.01em] text-dusk-ink">{title}</h3>
                <p className="mt-3 max-w-xs text-[15.5px] leading-7 text-dusk-mute">{copy}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* 2 · what it does, as an index (the pale petal ground) */}
      <section id="capabilities" className="bg-petal text-petal-ink">
        <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8 lg:px-10 lg:py-36">
          <div className="grid gap-10 lg:grid-cols-[1fr_0.9fr] lg:items-end lg:gap-24">
            <h2 className={`${serif} max-w-xl text-[clamp(2.6rem,5vw,4.6rem)]`}>Deploy the code. Keep the context.</h2>
            <p className="max-w-xl text-[17px] leading-8 text-petal-secondary">Rudder keeps the mechanics of shipping close to the work: services, configuration, release history, and the evidence behind every state.</p>
          </div>
          <div className="mt-20 grid gap-x-20 md:grid-cols-2">
            {features.map(([title, copy], index) => (
              <article key={title} className="grid grid-cols-[2.5rem_1fr] gap-4 border-t border-petal-line py-9">
                <span className="pt-1 font-mono text-[12px] text-accent-ink">0{index + 1}</span>
                <div>
                  <h3 className="text-[21px] font-medium leading-snug tracking-[-0.01em]">{title}</h3>
                  <p className="mt-3 max-w-md text-[15.5px] leading-7 text-petal-mute">{copy}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* 3 · where it sits, as a table (dusk raised) */}
      <section id="compare" className="bg-dusk-raised">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20 lg:px-10 lg:py-36">
          <div>
            <h2 className={`${serif} text-[clamp(2.4rem,4.2vw,4rem)]`}>Different tools. Different boundary.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-dusk-secondary">Rudder belongs with the developer who wants a fast delivery loop and a visible, self-hosted runtime—not a black box.</p>
          </div>
          <div className="overflow-x-auto rounded-[14px] bg-[#141114] p-[5px] shadow-[0_0_0_1px_rgba(255,255,255,.08),0_40px_90px_-40px_rgba(8,2,10,.8)]">
            <table className="w-full min-w-[560px] border-collapse rounded-[10px] bg-dusk text-left text-[15px]">
              <thead className="text-dusk-faint">
                <tr className="border-b border-dusk-line"><th className="px-5 py-4 font-normal">Approach</th><th className="px-5 py-4 font-normal">Best fit</th><th className="px-5 py-4 font-normal">Operating model</th></tr>
              </thead>
              <tbody className="divide-y divide-dusk-line text-dusk-secondary">
                <tr><th className="px-5 py-5 font-medium text-dusk-ink">Vercel</th><td className="px-5 py-5">Managed frontend delivery</td><td className="px-5 py-5">Platform-managed deployment experience</td></tr>
                <tr><th className="px-5 py-5 font-medium text-dusk-ink">Railway</th><td className="px-5 py-5">Managed app platform</td><td className="px-5 py-5">Platform-managed services and delivery</td></tr>
                <tr className="bg-accent/[0.06]"><th className="px-5 py-5 font-semibold text-accent">Rudder</th><td className="px-5 py-5 text-dusk-ink">Self-hosted apps and private services</td><td className="px-5 py-5 text-dusk-ink">Your service graph, releases, and operator control</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* 4 · where it runs, as a status board (petal) */}
      <section id="platforms" className="bg-petal text-petal-ink">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.85fr_1.15fr] lg:gap-20 lg:px-10 lg:py-36">
          <div>
            <h2 className={`${serif} text-[clamp(2.4rem,4.2vw,4rem)]`}>Start where you are.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-petal-secondary">Build on your laptop with the same product model you use to evaluate a Kubernetes target.</p>
          </div>
          <ul className="divide-y divide-petal-line border-y border-petal-line">
            {platforms.map(([name, copy, state, dot]) => (
              <li key={name} className="grid grid-cols-[1fr_auto] items-start gap-6 py-7">
                <div>
                  <h3 className="text-[19px] font-medium tracking-[-0.01em]">{name}</h3>
                  <p className="mt-2 max-w-lg text-[15.5px] leading-7 text-petal-mute">{copy}</p>
                </div>
                <span className="mt-1 inline-flex items-center gap-2 rounded-full bg-white/60 px-3 py-1 text-[12.5px] font-medium text-petal-secondary ring-1 ring-petal-line">
                  <span aria-hidden className={`h-2 w-2 rounded-full ${dot}`} />
                  {state}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* 5 · the closing scene: back to the hills, with the commands in a window */}
      <section id="run-locally" className="relative isolate overflow-hidden">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={HILLS} alt="" aria-hidden className="absolute inset-0 -z-10 h-full w-full object-cover object-[50%_58%]" />
        <div aria-hidden className="absolute inset-0 -z-10 bg-[linear-gradient(180deg,rgba(20,12,18,.92)_0%,rgba(20,12,18,.55)_45%,rgba(20,12,18,.9)_100%)]" />
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-28 sm:px-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-center lg:gap-20 lg:px-10 lg:py-40">
          <div>
            <h2 className={`${serif} text-[clamp(2.6rem,5vw,4.6rem)] text-white`}>Run Rudder locally.</h2>
            <p className="mt-6 max-w-md text-[17px] leading-8 text-dusk-secondary">Bring up the stack, migrate the control plane, then connect GitHub from the browser. Full environment guidance stays in the repository.</p>
            <div className="mt-9 flex flex-wrap items-center gap-6">
              <a className="inline-flex items-center gap-2 text-[15px] font-medium text-dusk-ink underline-offset-4 hover:underline" href="https://github.com/sidhxntt/rudder#setup" target="_blank" rel="noreferrer">
                Read the setup guide <ArrowRight />
              </a>
            </div>
          </div>
          <div className="min-w-0 rounded-[14px] bg-[#141114] p-[5px] shadow-[0_0_0_1px_rgba(255,255,255,.1),0_40px_90px_-30px_rgba(8,2,10,.7),0_0_120px_-20px_rgba(255,190,170,.12)]">
            <div className="flex items-center gap-1.5 px-3 py-2.5" aria-hidden>
              <span className="h-2.5 w-2.5 rounded-full bg-white/15" /><span className="h-2.5 w-2.5 rounded-full bg-white/15" /><span className="h-2.5 w-2.5 rounded-full bg-white/15" />
              <span className="ml-3 font-mono text-[11px] text-dusk-faint">rudder · zsh</span>
            </div>
            <pre className="overflow-x-auto rounded-[10px] bg-surface-inset p-6 font-mono text-[13.5px] leading-8 text-ink-secondary"><code><span className="text-ink-faint"># configure local secrets</span>{"\n"}cp .env.example .env{"\n\n"}<span className="text-ink-faint"># start the local control plane</span>{"\n"}docker compose -f docker-compose.dev.yml up -d{"\n"}docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head{"\n"}docker compose -f docker-compose.dev.yml restart control-plane</code></pre>
          </div>
        </div>
      </section>

      <footer className="border-t border-dusk-line bg-dusk">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-9 text-[14px] text-dusk-mute sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
          <span className="text-[18px] font-semibold tracking-[-0.02em] text-dusk-ink">rudder</span>
          <div className="flex gap-6">
            <a className="hover:text-dusk-ink" href="https://github.com/sidhxntt/rudder" target="_blank" rel="noreferrer">GitHub</a>
            <a className="hover:text-dusk-ink" href="https://github.com/sidhxntt/rudder/tree/main/docs" target="_blank" rel="noreferrer">Documentation</a>
            <Link className="hover:text-dusk-ink" href={authenticated ? "/dashboard" : "/api/auth/github/start"}>{authenticated ? "Workspace" : "Sign in"}</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
