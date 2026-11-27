"use client";
// Construct Design · tessel. Its motion is tuned by hand: leave the physics. https://www.tobiadonadon.com/projects/construct/design?block=tessel

/**
 * RUDDER · website hero (adapted from the "Tessel" hero design)
 *
 * The first screen of Rudder, a self-hosted PaaS. A real photograph at dusk:
 * rolling hills covered in lilac and peach blossom under a dim violet sky. A
 * light, tight serif headline sits centred in the sky over a small sans line,
 * a white pill button and a short note. Below it Rudder's own window (a dark
 * sidebar, a breadcrumb, the release bar, a flowchart of the control plane and
 * an inspector) rises out of the landscape: the near treeline is a cut-out
 * layer IN FRONT of the window, so the app looks planted between the far hills
 * and the trees.
 *
 * The signature: the control plane runs a release by itself. A token of light
 * travels the connectors from step to step (GitHub push, Resolve & build,
 * Healthy?, then Shift traffic or Mark failed, taking the other branch on
 * the next run), each step lights as it is reached and gets a tick when it is
 * done, the inspector follows the running step, and at the end the status
 * spins "Recording…" and ticks back to "Recorded just now". A collaborator's
 * cursor drifts over the canvas. On a desktop the pointer parts the three
 * planes (sky, window, trees) a little. Click a step to select it (the
 * inspector shows it); Deploy runs deploying, then deployed with a tick.
 *
 * The flowchart is the control plane's logic, in the API's own vocabulary:
 * a push on a connected branch → the Compose graph is resolved and the image
 * built (Deployment queued → building) → the new Instance is health-checked
 * (deploying) → healthy: traffic shifts and the Deployment is live; not
 * healthy: the Deployment is failed. A build that fails stops there and keeps
 * the current release; every run is recorded with its logs, state and restore
 * point.
 *
 * One file, React only. Typefaces from Google Fonts (loaded in the CSS):
 * Fraunces 300 (upright, never italic) for the headline, Inter Tight for
 * everything else.
 *
 *   <RudderHero />
 *   <RudderHero speed={1.4} cta={{ label: "Deploy from GitHub", href: "/dashboard?import=github" }} />
 *
 * Props
 *   brand     the wordmark                                  "Rudder"
 *   headline  two lines, split by "\n"                      "Push the code.\nRudder leaves the trail."
 *   pill      the small line above the headline ("" hides)  "In development"
 *   sub       the line under the headline
 *   cta       the white button                              Sign in with GitHub → /api/auth/github/start
 *   signIn    the smoked nav button                         Sign in → /api/auth/github/start
 *   links     the nav links
 *   accent    the running token and the selected step       "#3ecf8e"
 *   speed     how fast the release runs, 1 = normal         1
 *   hills     the photograph: sky and far hills             "/design/websites/tessel/hills.webp"
 *   treeline  the near trees, a transparent cut-out         "/design/websites/tessel/treeline.webp"
 *   sound     a soft tick on select, a chime on deploy      true
 *   autoplay  the release runs by itself                    true
 *   onStart   called when the white button is pressed
 *
 * Fills its container's width; height is var(--design-h, 100svh), never
 * under 640px. On a phone the headline is sized by the width and the window
 * is cropped to the release bar and the canvas, still rising from the trees.
 * Keyboard: every nav item, button and step is real; Enter or Space on a step
 * selects it.
 * Depth: the sky, the window and the trees are three planes; under a mouse they
 * part (the sky one way, the trees the other, three times as far).
 * Self-play: the run loops on its own and the inspector follows it; a click
 * pins your selection for six seconds. Everything pauses off screen and in
 * a hidden tab.
 * Reduced motion: one finished frame (Resolve & build running, the first
 * connector lit), no parallax, no drift; selecting and deploying still work.
 * Sound: silent until the visitor interacts, when `sound` is false, and
 * under <html data-cd-mute="1">.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

type HeroLink = { label: string; href: string };
type Props = {
  brand?: string;
  headline?: string;
  pill?: string;
  sub?: string;
  cta?: HeroLink;
  signIn?: HeroLink;
  links?: HeroLink[];
  accent?: string;
  speed?: number;
  hills?: string;
  treeline?: string;
  sound?: boolean;
  autoplay?: boolean;
  onStart?: () => void;
};

/* ------------------------------------------------------------------ sound
   A tiny synthesized tick or chime, made in the browser. Silent when `sound`
   is false, under <html data-cd-mute="1">, and until the visitor has touched
   the page. Delete this hook and its calls to make it silent for good. */
function useTone(on: boolean) {
  const ctx = useRef<AudioContext | null>(null);
  useEffect(() => () => void ctx.current?.close().catch(() => {}), []);
  return useCallback(
    (notes: [number, number, number][]) => {
      if (!on || typeof window === "undefined") return;
      if (document.documentElement.dataset.cdMute === "1") return;
      const ua = (navigator as unknown as { userActivation?: { hasBeenActive: boolean } }).userActivation;
      if (ua && !ua.hasBeenActive) return;
      try {
        const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AC) return;
        const a = (ctx.current ??= new AC());
        if (a.state === "suspended") void a.resume();
        const t0 = a.currentTime;
        for (const [f, at, d] of notes) {
          const t = t0 + at;
          const amp = a.createGain();
          amp.gain.setValueAtTime(0.0001, t);
          amp.gain.exponentialRampToValueAtTime(0.04, t + 0.004);
          amp.gain.exponentialRampToValueAtTime(0.0001, t + d);
          amp.connect(a.destination);
          const o = a.createOscillator();
          o.type = "sine";
          o.frequency.setValueAtTime(f, t);
          o.connect(amp);
          o.start(t);
          o.stop(t + d + 0.01);
        }
      } catch {
        /* sound is a nicety */
      }
    },
    [on],
  );
}

/* ------------------------------------------------------------ the canvas
   Everything on the canvas lives in one coordinate system (design px); the
   nodes are HTML placed with left/top, the connectors one SVG on top. */
type Kind = "trigger" | "check" | "branch" | "action" | "stop" | "log";
type Node = { x: number; y: number; w: number; kind: Kind; title: string; sub: string; chips?: string[]; next: string };
const NODES: Node[] = [
  { x: 28, y: 50, w: 172, kind: "trigger", title: "GitHub push", sub: "Webhook on main", next: "Resolve & build" },
  { x: 28, y: 142, w: 172, kind: "check", title: "Resolve & build", sub: "Compose graph → image", chips: ["app", "db", "cache", "worker"], next: "Healthy?" },
  { x: 236, y: 153, w: 132, kind: "branch", title: "Healthy?", sub: "New instance", next: "Shift traffic" },
  { x: 404, y: 92, w: 144, kind: "action", title: "Shift traffic", sub: "Deployment → live", next: "Record release" },
  { x: 404, y: 214, w: 144, kind: "action", title: "Mark failed", sub: "Deployment → failed", next: "Record release" },
  { x: 236, y: 60, w: 168, kind: "stop", title: "Build failed, keep current", sub: "", next: "Stream the build log" },
  { x: 28, y: 256, w: 172, kind: "log", title: "Record release", sub: "Logs, state, restore point", next: "End" },
];
/* run edges first: 0 push→build, 1 build→health check, 2 healthy→shift traffic, 3 unhealthy→mark failed */
const EDGES = [
  "M114 104 V142",
  "M200 180 H236",
  "M368 180 H380 Q386 180 386 174 V125 Q386 119 392 119 H404",
  "M368 180 H380 Q386 180 386 186 V235 Q386 241 392 241 H404",
  "M200 158 H210 Q218 158 218 150 V83 Q218 75 226 75 H236",
  "M114 218 V256",
];
const LABELS: [number, number, string][] = [[218, 118, "failed"], [386, 150, "healthy"], [386, 211, "unhealthy"]];
type Step = { k: "node"; n: number; d: number } | { k: "edge"; e: number; d: number } | { k: "save"; d: number } | { k: "rest"; d: number };
const runOf = (b: number): Step[] => [
  { k: "node", n: 0, d: 650 },
  { k: "edge", e: 0, d: 420 },
  { k: "node", n: 1, d: 950 },
  { k: "edge", e: 1, d: 420 },
  { k: "node", n: 2, d: 700 },
  { k: "edge", e: b ? 3 : 2, d: 780 },
  { k: "node", n: b ? 4 : 3, d: 950 },
  { k: "save", d: 950 },
  { k: "rest", d: 1500 },
];
const r2 = (n: number) => Math.round(n * 100) / 100;
const W = (n: number) => `calc(${n} * var(--w))`;
const U = (n: number) => `calc(${n} * var(--u))`;

function Glyph({ kind }: { kind: Kind }) {
  switch (kind) {
    case "trigger":
      return <svg viewBox="0 0 16 16" aria-hidden><path d="M9.2 2.5L4.6 9h3.3l-1 4.5L11.4 7H8.1z" fill="#fff" /></svg>;
    case "check":
      return <svg viewBox="0 0 16 16" aria-hidden><path d="M4.6 8.3l2.2 2.2 4.6-4.8" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
    case "branch":
      return <svg viewBox="0 0 16 16" aria-hidden><path d="M4 8h3.5M7.5 8c1.5 0 1.6-3 3.4-3H12M7.5 8c1.5 0 1.6 3 3.4 3H12" fill="none" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" /></svg>;
    case "action":
      return <svg viewBox="0 0 16 16" aria-hidden><path d="M6 4.6v6.8L11.4 8z" fill="#fff" /></svg>;
    case "stop":
      return <svg viewBox="0 0 16 16" aria-hidden><rect x="5.2" y="5.2" width="5.6" height="5.6" rx="1.2" fill="#fff" /></svg>;
    default:
      return <svg viewBox="0 0 16 16" aria-hidden><path d="M4.5 5.5h7M4.5 8h7M4.5 10.5h4.5" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" /></svg>;
  }
}

const Ico = {
  home: "M3 7.5L8 3.5l5 4V13H9.5V9.8h-3V13H3z",
  flow: "M4 3.5h3v3H4zM9 9.5h3v3H9zM5.5 6.5v2.2c0 1 .5 1.8 1.8 1.8H9",
  key: "M10 3.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5zM8.2 7.8L3.5 12.5M5 11l1.4 1.4",
  table: "M3 4h10v8H3zM3 7h10M7 4v8",
  rocket: "M8 2.8c2 1.4 3 3.4 3 5.8V11H5V8.6c0-2.4 1-4.4 3-5.8zM6.4 13.2h3.2M8 6.5v.01",
  chart: "M3.5 12.5h9M5 10.5V8M8 10.5V5M11 10.5V7",
};

const LINKS: HeroLink[] = [
  { label: "Capabilities", href: "#capabilities" },
  { label: "Delivery loop", href: "#delivery-loop" },
  { label: "Compare", href: "#compare" },
  { label: "Platforms", href: "#platforms" },
  { label: "Docs", href: "https://github.com/sidhxntt/rudder/tree/main/docs" },
];
const external = (href: string) => (/^https?:/.test(href) ? { target: "_blank", rel: "noreferrer" } : {});

export default function RudderHero({
  brand = "Rudder",
  headline = "Push the code.\nRudder leaves the trail.",
  pill = "In development",
  sub = "Rudder turns the repository you already trust into a release you can inspect: its application, private services, runtime state, and route to recovery.",
  cta = { label: "Sign in with GitHub", href: "/api/auth/github/start" },
  signIn = { label: "Sign in", href: "/api/auth/github/start" },
  links = LINKS,
  accent = "#3ecf8e",
  speed = 1,
  hills = "/design/websites/tessel/hills.webp",
  treeline = "/design/websites/tessel/treeline.webp",
  sound = true,
  autoplay = true,
  onStart,
}: Props) {
  const root = useRef<HTMLDivElement>(null);
  const fills = useRef<(SVGPathElement | null)[]>([]);
  const guides = useRef<(SVGPathElement | null)[]>([]);
  const token = useRef<SVGGElement>(null);
  const lit = useRef<SVGGElement>(null);
  const mate = useRef<HTMLDivElement>(null);
  const tone = useTone(sound);

  /* the first painted frame: Validate running, the first connector lit */
  const [active, setActive] = useState(1);
  const [done, setDone] = useState(1);
  const [selected, setSelected] = useState(1);
  const [saving, setSaving] = useState(false);
  const [pub, setPub] = useState<"idle" | "busy" | "done">("idle");
  const live = useRef({ speed, autoplay, pinnedUntil: 0, lastTouch: -1e9 });
  live.current.speed = speed;
  live.current.autoplay = autoplay;

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const fine = window.matchMedia("(pointer: fine)");
    let seen = true, raf = 0, prev = 0, T = 0;
    const ptr = { x: 0, y: 0, on: false }, cam = { x: 0, y: 0 };

    /* ---- the run ---- */
    let branch = 0, steps = runOf(branch), si = 2, st = 0, doneMask = 1;
    const lens = guides.current.map((p) => { try { return p?.getTotalLength() ?? 1; } catch { return 1; } });
    const setFill = (e: number, p: number) => {
      const f = fills.current[e];
      if (f) f.style.strokeDashoffset = String(r2(1 - p));
    };
    const showToken = (on: boolean) => { if (token.current) token.current.style.opacity = on ? "1" : "0"; };
    const place = (e: number, p: number) => {
      const g = guides.current[e], tk = token.current;
      if (!g || !tk) return;
      try {
        const pt = g.getPointAtLength(lens[e] * p);
        tk.setAttribute("transform", `translate(${r2(pt.x)} ${r2(pt.y)})`);
      } catch { /* not laid out */ }
    };
    const enter = (s: Step) => {
      if (s.k === "node") {
        setActive(s.n);
        showToken(false);
        if (performance.now() > live.current.pinnedUntil) setSelected(s.n);
      } else if (s.k === "edge") {
        const from = steps[si - 1];
        if (from && from.k === "node") { doneMask |= 1 << from.n; setDone(doneMask); }
        setActive(-1);
        showToken(true);
      } else if (s.k === "save") {
        const from = steps[si - 1];
        if (from && from.k === "node") { doneMask |= 1 << from.n; setDone(doneMask); }
        setActive(-1);
        setSaving(true);
      } else {
        setSaving(false);
      }
    };
    const restart = () => {
      branch = 1 - branch;
      steps = runOf(branch);
      si = 0; st = 0; doneMask = 0;
      setDone(0);
      if (lit.current) lit.current.style.opacity = "1";
      for (let e = 0; e < 4; e++) setFill(e, 0);
      enter(steps[0]);
    };
    const tick = (dt: number) => {
      const s = steps[si];
      st += dt * Math.max(0.3, live.current.speed);
      const p = Math.min(1, st / s.d);
      if (s.k === "edge") {
        const q = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
        setFill(s.e, q);
        place(s.e, q);
      }
      if (s.k === "rest" && lit.current) lit.current.style.opacity = p > 0.62 ? "0" : "1";
      if (st >= s.d) {
        if (s.k === "edge") showToken(false);
        st = 0;
        si++;
        if (si >= steps.length) restart();
        else enter(steps[si]);
      }
    };

    const frame = (dt: number, now: number) => {
      T += dt / 1000;
      if (live.current.autoplay) tick(dt);
      // a collaborator's cursor drifts round the Validate node
      if (mate.current) {
        const mx = Math.sin(T * 0.42) * 14 + Math.sin(T * 0.97) * 4, my = Math.cos(T * 0.31) * 8 + Math.sin(T * 1.3) * 2;
        mate.current.style.translate = `calc(${r2(mx)} * var(--w)) calc(${r2(my)} * var(--w))`;
      }
      // three planes part a little: on their own, and under a mouse
      const useP = ptr.on && fine.matches;
      const gx = useP ? ptr.x : Math.sin(T * 0.19) * 0.3, gy = useP ? ptr.y : Math.sin(T * 0.13 + 1) * 0.25;
      const k = 1 - Math.exp(-dt / (useP ? 380 : 1100));
      cam.x += (gx - cam.x) * k; cam.y += (gy - cam.y) * k;
      el.style.setProperty("--px", cam.x.toFixed(3));
      el.style.setProperty("--py", cam.y.toFixed(3));
      void now;
    };
    const loop = (now: number) => {
      raf = 0;
      const dt = Math.min(50, now - (prev || now));
      prev = now;
      frame(dt, now);
      if (seen && !document.hidden && !reduced.matches) raf = requestAnimationFrame(loop);
      else prev = 0;
    };
    const kick = () => {
      el.dataset.off = seen && !document.hidden ? "0" : "1";
      if (!raf && seen && !document.hidden && !reduced.matches) raf = requestAnimationFrame(loop);
    };
    const move = (e: PointerEvent) => {
      live.current.lastTouch = performance.now();
      if (e.pointerType !== "mouse") return;
      const r = el.getBoundingClientRect();
      ptr.x = ((e.clientX - r.left) / r.width) * 2 - 1; ptr.y = ((e.clientY - r.top) / r.height) * 2 - 1; ptr.on = true;
    };
    const leave = () => { ptr.on = false; };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    const io = new IntersectionObserver(([e]) => { seen = e.isIntersecting; kick(); });
    io.observe(el);
    document.addEventListener("visibilitychange", kick);
    reduced.addEventListener?.("change", kick);
    kick();
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      document.removeEventListener("visibilitychange", kick);
      reduced.removeEventListener?.("change", kick);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
  }, []);

  /* publish: publishing → published with a tick → back to the draft (demo reset) */
  useEffect(() => {
    if (pub === "idle") return;
    const id = window.setTimeout(() => setPub(pub === "busy" ? "done" : "idle"), pub === "busy" ? 950 : 2000);
    return () => window.clearTimeout(id);
  }, [pub]);

  const pick = (i: number) => {
    live.current.pinnedUntil = performance.now() + 6000;
    setSelected(i);
    tone([[1320, 0, 0.04]]);
  };
  const publish = () => {
    if (pub !== "idle") return;
    setPub("busy");
    tone([[880, 0, 0.05], [1320, 0.95, 0.09], [1760, 1.03, 0.12]]);
  };

  const [l1, l2] = headline.split("\n");
  const sel = NODES[selected] ?? NODES[1];

  return (
    <div ref={root} className="tsl-root" style={{ "--acc": accent } as CSSProperties}>
      <style>{css}</style>
      <div className="tsl-in">
        <div className="tsl-sky" aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={hills} alt="" draggable={false} />
          <i className="tsl-glow" />
        </div>

        <header className="tsl-nav">
          <a className="tsl-logo" href="/" aria-label={`${brand} home`}>
            <svg viewBox="0 0 20 20" aria-hidden>
              <circle cx="10" cy="10" r="6.2" fill="none" stroke="currentColor" strokeWidth="2.2" /><circle cx="10" cy="10" r="2.3" /><path d="M10 1.2v3.4M10 15.4v3.4M1.2 10h3.4M15.4 10h3.4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
            {brand.toLowerCase()}
          </a>
          <nav className="tsl-links" aria-label="Main">
            {links.map((l) => (
              <a key={l.label} href={l.href} {...external(l.href)}>{l.label}</a>
            ))}
          </nav>
          <div className="tsl-acts">
            <a className="tsl-login" href="#run-locally">Run locally</a>
            <a className="tsl-get" href={signIn.href}>{signIn.label}</a>
            <a className="tsl-menu" href="#capabilities" aria-label="More about Rudder"><i /><i /></a>
          </div>
        </header>

        <section className="tsl-copy">
          {pill ? <p className="tsl-pill"><i aria-hidden />{pill}</p> : null}
          <h1 className="tsl-h1"><span>{l1}</span> <span>{l2}</span></h1>
          <p className="tsl-sub">{sub}</p>
          <div className="tsl-row">
            <a className="tsl-cta" href={cta.href} onClick={onStart}>
              <svg viewBox="0 0 24 24" aria-hidden><path d="M12 2C6.48 2 2 6.48 2 12.02c0 4.42 2.87 8.18 6.84 9.5.5.09.68-.22.68-.48l-.01-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.95 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.03A9.56 9.56 0 0 1 12 6.34c.85 0 1.71.11 2.5.34 1.91-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.85-2.34 4.7-4.57 4.94.36.31.68.92.68 1.86l-.01 2.75c0 .27.18.58.69.48A10.02 10.02 0 0 0 22 12.02C22 6.48 17.52 2 12 2Z" /></svg>
              {cta.label}
            </a>
            <div className="tsl-rate">
              <span><svg viewBox="0 0 16 16" aria-hidden><path d="M3 3.5h10v3.6H3zM3 8.9h10v3.6H3zM5.2 5.3h.01M5.2 10.7h.01" /></svg>Self-hosted</span>
              <small>single-tenant by design</small>
            </div>
          </div>
        </section>

        {/* the product's window, rising out of the landscape */}
        <div className="tsl-win" role="group" aria-label="Rudder control plane, running a sample release">
          <aside className="tsl-side" aria-hidden>
            <div className="tsl-side-top">
              <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="6.2" fill="none" stroke="currentColor" strokeWidth="2.2" /><circle cx="10" cy="10" r="2.3" /><path d="M10 1.2v3.4M10 15.4v3.4M1.2 10h3.4M15.4 10h3.4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
              <b>{brand.toLowerCase()}</b>
              <i className="tsl-col" />
            </div>
            <div className="tsl-search"><svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4" /><path d="M10 10l3 3" /></svg>Search<kbd>⌘K</kbd></div>
            <p className="tsl-h">Overview</p>
            {([["home", "Workspace"], ["flow", "Service graph"], ["rocket", "Deployments"], ["key", "Variables"], ["chart", "Analytics"]] as const).map(([k, l]) => (
              <p key={k} className="tsl-it"><svg viewBox="0 0 16 16"><path d={Ico[k]} /></svg>{l}</p>
            ))}
            <p className="tsl-h">Projects <i className="tsl-plus">+</i></p>
            {([["shop", "#7fc8a9"], ["api", "#f2b66d"], ["docs-site", "#8fa8ff"], ["billing", "#e9a0c4"]] as const).map(([l, c], i) => (
              <p key={l} className={`tsl-it tsl-proj${i === 0 ? " tsl-on" : ""}`}><i style={{ background: c }} />{l}<svg viewBox="0 0 16 16"><path d="M5.5 6.5L8 9l2.5-2.5" /></svg></p>
            ))}
          </aside>

          <div className="tsl-main">
            <div className="tsl-top">
              <p className="tsl-crumb">Projects <i>/</i> shop <i>/</i> <b>production</b></p>
              <div className="tsl-top-r" aria-hidden>
                <span className="tsl-ib"><svg viewBox="0 0 16 16"><path d="M3.5 4.5h9v6h-5l-2.5 2v-2h-1.5z" /></svg></span>
                <span className="tsl-ib"><svg viewBox="0 0 16 16"><path d="M5 11V7.5a3 3 0 0 1 6 0V11l1 1H4zM7 13.2h2" /></svg></span>
                <span className="tsl-hist">Deploy history</span>
                <span className="tsl-me">SD</span>
              </div>
            </div>

            <div className="tsl-bar">
              <span className="tsl-back" aria-hidden><svg viewBox="0 0 16 16"><path d="M12.5 8h-9M7 4.5L3.5 8 7 11.5" /></svg></span>
              <b className="tsl-name">Release · shop</b>
              <span className={`tsl-tag${pub === "done" ? " tsl-live" : ""}`}>{pub === "done" ? "Live" : "Staged"}</span>
              <span className="tsl-sp" />
              <span className={`tsl-saved${saving ? " tsl-busy" : ""}`} aria-live="polite">
                <svg viewBox="0 0 16 16" aria-hidden><path d="M12.6 6.4A4.8 4.8 0 0 0 3.7 5.6M3.4 9.6a4.8 4.8 0 0 0 8.9.8M3.6 3.2v2.6h2.6M12.4 12.8v-2.6H9.8" /></svg>
                <span>{saving ? "Recording…" : <>Recorded<span className="tsl-jn"> just now</span></>}</span>
              </span>
              <span className="tsl-avs" aria-hidden><i style={{ background: "#c9b6ff" }}>AK</i><i style={{ background: "#9fd8c2" }}>JR</i><i style={{ background: "#ffc9a3" }}>LT</i></span>
              <span className="tsl-div" aria-hidden />
              <button type="button" className="tsl-draft">Build log</button>
              <button type="button" className={`tsl-pub tsl-pub-${pub}`} onClick={publish} aria-live="polite">
                {pub === "busy" && <i className="tsl-spin" aria-hidden />}
                {pub === "done" && <svg viewBox="0 0 16 16" aria-hidden><path d="M4 8.4l2.6 2.5L12 5.5" /></svg>}
                {pub === "idle" ? "Deploy" : pub === "busy" ? "Deploying" : "Deployed"}
              </button>
            </div>

            <div className="tsl-canvas">
              <div className="tsl-tools" aria-hidden><span>↶</span><span>↷</span></div>
              <div className="tsl-zoom" aria-hidden><span>−</span>80%<span>+</span></div>
              <div className="tsl-plane">
                <svg className="tsl-wires" viewBox="0 0 560 330" aria-hidden>
                  {EDGES.map((d, i) => (
                    <path key={i} ref={(p) => { guides.current[i] = p; }} d={d} className={`tsl-wire${i >= 4 ? " tsl-dash" : ""}`} />
                  ))}
                  <g ref={lit}>
                    {EDGES.slice(0, 4).map((d, i) => (
                      <path key={i} ref={(p) => { fills.current[i] = p; }} d={d} pathLength={1} className="tsl-fill" style={{ strokeDashoffset: i === 0 ? 0 : 1 }} />
                    ))}
                  </g>
                  {LABELS.map(([x, y, t]) => (
                    <g key={t} transform={`translate(${x} ${y})`}>
                      <rect x={-t.length * 2.3 - 4} y={-6.5} width={t.length * 4.6 + 8} height={13} rx={6.5} className="tsl-lab" />
                      <text textAnchor="middle" y={2.6}>{t}</text>
                    </g>
                  ))}
                  <g ref={token} className="tsl-token" style={{ opacity: 0 }} transform="translate(114 104)">
                    <circle r="9" className="tsl-halo" />
                    <circle r="3.6" />
                  </g>
                </svg>
                {NODES.map((n, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`tsl-node tsl-k-${n.kind}${active === i ? " tsl-act" : ""}${done & (1 << i) ? " tsl-done" : ""}${selected === i ? " tsl-sel" : ""}`}
                    style={{ left: W(n.x), top: W(n.y), width: W(n.w) }}
                    aria-pressed={selected === i}
                    onClick={() => pick(i)}
                  >
                    <span className="tsl-nh">
                      <span className="tsl-gl"><Glyph kind={n.kind} /></span>
                      <b>{n.title}</b>
                      {n.kind !== "stop" && <span className="tsl-st" aria-hidden><svg viewBox="0 0 16 16"><path d="M4.5 8.4l2.3 2.2 4.7-4.9" /></svg></span>}
                    </span>
                    {n.sub && <span className="tsl-ns">{n.sub}</span>}
                    {n.chips && <span className="tsl-chips">{n.chips.map((c) => <i key={c}>{c}</i>)}</span>}
                  </button>
                ))}
                <div ref={mate} className="tsl-mate" aria-hidden style={{ left: W(214), top: W(226) }}>
                  <svg viewBox="0 0 16 16"><path d="M2.5 1.8l10 5.6-4.4 1.1-2 4.3z" /></svg>
                  <span>Looks good</span>
                </div>
              </div>
            </div>

            <aside className="tsl-insp" aria-live="polite">
              <div className="tsl-ih">
                <span className={`tsl-gl tsl-k-${sel.kind}`}><Glyph kind={sel.kind} /></span>
                <b>{sel.title.length > 18 ? "Build failed" : sel.title}</b>
                <span className="tsl-x" aria-hidden>×</span>
              </div>
              <p className="tsl-field">{sel.sub || "Keep the live release"}<svg viewBox="0 0 16 16" aria-hidden><path d="M10.5 3.5l2 2-6.5 6.5H4v-2z" /></svg></p>
              <p className="tsl-ilab">Next step<svg viewBox="0 0 16 16" aria-hidden><path d="M5.5 6.5L8 9l2.5-2.5" /></svg></p>
              <p className="tsl-ihint">What the control plane does next</p>
              <p className="tsl-sel-box"><span className="tsl-yy">Y</span>{sel.next}<svg viewBox="0 0 16 16" aria-hidden><path d="M5.5 6L8 3.5 10.5 6M5.5 10L8 12.5 10.5 10" /></svg></p>
              <p className="tsl-cond"><b>True</b><i />{sel.kind === "check" ? "if the image builds" : sel.kind === "branch" ? "if healthy" : "on success"}</p>
              <p className="tsl-cond tsl-cond2"><b>Last run</b>42 s</p>
            </aside>
          </div>
        </div>

        <div className="tsl-trees" aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={treeline} alt="" draggable={false} />
        </div>
        <i className="tsl-floor" aria-hidden />

        <footer className="tsl-foot">
          <p className="tsl-proof">GitHub is the sign-in<br />and repository boundary.</p>
          <ul className="tsl-stats">
            <li><b>Control</b> your runtime boundary</li>
            <li><b>Evidence</b> logs, state, restore</li>
            <li><b>GKE</b> controlled beta</li>
          </ul>
        </footer>
      </div>
    </div>
  );
}

const css = `
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300&family=Inter+Tight:wght@400;500;600&display=swap");

.tsl-root { --acc: #3ecf8e; --px: 0; --py: 0; position: relative; width: 100%; height: var(--design-h, 100svh); min-height: 640px; overflow: hidden; isolation: isolate;
  container-type: size; background: #1d1519; color: #fff; font-family: "Inter Tight", "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; }
.tsl-root *, .tsl-root *::before, .tsl-root *::after { box-sizing: border-box; }
.tsl-root[data-off="1"] * { animation-play-state: paused !important; }
.tsl-in { --u: min(calc(100cqw / 1440), calc(100cqh / 900)); --w: var(--u); --wy: ${U(458)}; position: absolute; inset: 0; }
.tsl-root :where(p, h1, ul) { margin: 0; padding: 0; }
.tsl-root button { font: inherit; color: inherit; }
.tsl-root { line-height: normal; } /* the host page sets 1.45 */

/* the sky and the far hills */
.tsl-sky { position: absolute; inset: -3%; translate: calc(var(--px) * ${U(14)}) calc(var(--py) * ${U(7)}); }
.tsl-sky img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 58%; display: block; }
.tsl-glow { position: absolute; inset: 0; background:
  radial-gradient(34% 16% at 50% 56%, rgba(255,196,170,.16), transparent 70%),
  linear-gradient(180deg, rgba(20,12,22,.5) 0%, rgba(20,12,22,.12) 34%, transparent 52%); }

/* nav */
.tsl-nav { position: absolute; left: 0; right: 0; top: ${U(26)}; z-index: 5; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; padding: 0 ${U(40)}; }
.tsl-logo { display: inline-flex; align-items: center; gap: ${U(9)}; color: #fff; text-decoration: none; font-size: ${U(19)}; font-weight: 600; letter-spacing: -.02em; justify-self: start; border-radius: 6px; }
.tsl-logo svg { width: ${U(21)}; height: ${U(21)}; fill: #fff; color: #fff; }
.tsl-links { display: flex; gap: ${U(34)}; }
.tsl-links a { color: rgba(255,255,255,.86); text-decoration: none; font-size: ${U(14)}; font-weight: 500; letter-spacing: -.005em; border-radius: 4px; transition: color .2s; }
.tsl-links a:hover { color: #fff; }
.tsl-acts { justify-self: end; display: flex; gap: ${U(8)}; align-items: center; }
.tsl-login, .tsl-get { display: inline-flex; align-items: center; height: ${U(38)}; padding: 0 ${U(19)}; border-radius: 999px; font-size: ${U(13.5)}; font-weight: 500; text-decoration: none; letter-spacing: -.005em; transition: transform .2s cubic-bezier(.3,1.4,.5,1), background .2s; }
.tsl-login { background: #fff; color: #141014; }
.tsl-get { background: rgba(22,15,20,.72); color: #fff; box-shadow: inset 0 0 0 1px rgba(255,255,255,.12); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }
.tsl-login:active, .tsl-get:active, .tsl-cta:active { transform: scale(.97); }
.tsl-menu { display: none; }
.tsl-root a:focus-visible, .tsl-root button:focus-visible { outline: 2px solid #fff; outline-offset: 3px; }

/* headline block */
.tsl-copy { position: absolute; left: 0; right: 0; top: ${U(84)}; z-index: 4; display: flex; flex-direction: column; align-items: center; text-align: center; }
.tsl-pill { display: inline-flex; align-items: center; height: ${U(31)}; padding: 0 ${U(16)}; border-radius: 999px; font-size: ${U(13)}; color: rgba(255,255,255,.84); letter-spacing: -.003em;
  background: rgba(30,20,28,.32); box-shadow: inset 0 0 0 1px rgba(255,255,255,.15); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); gap: ${U(8)}; }
.tsl-pill i { width: ${U(6)}; height: ${U(6)}; border-radius: 50%; background: #f5c400; box-shadow: 0 0 0 ${U(3)} rgba(245,196,0,.2); }
.tsl-h1 { margin-top: ${U(20)}; font-family: Fraunces, "Times New Roman", serif; font-weight: 300; font-style: normal; font-variation-settings: "opsz" 144, "SOFT" 0, "WONK" 0; font-size: ${U(66)}; line-height: 1; letter-spacing: -.045em; color: #fff;
  text-shadow: 0 1px 30px rgba(20,10,20,.25); }
.tsl-h1 span { display: block; white-space: nowrap; }
.tsl-sub { margin-top: ${U(14)}; max-width: ${U(520)}; font-size: ${U(16)}; line-height: 1.42; color: rgba(236,226,236,.64); letter-spacing: -.004em; }
.tsl-row { margin-top: ${U(22)}; display: flex; align-items: center; gap: ${U(26)}; }
.tsl-cta { display: inline-flex; align-items: center; gap: ${U(9)}; text-decoration: none; height: ${U(48)}; padding: 0 ${U(26)}; border: 0; border-radius: 999px; background: #fff; color: #141014 !important; font-size: ${U(15)} !important; font-weight: 500; letter-spacing: -.008em; cursor: pointer;
  box-shadow: 0 10px 30px -12px rgba(0,0,0,.5); transition: transform .22s cubic-bezier(.3,1.4,.5,1); }
.tsl-cta:hover { transform: translateY(-1px); }
.tsl-cta svg { width: ${U(17)}; height: ${U(17)}; fill: currentColor; }
.tsl-rate { display: grid; text-align: left; gap: ${U(3)}; }
.tsl-rate span { display: inline-flex; align-items: center; gap: ${U(6)}; font-size: ${U(17)}; font-weight: 500; font-variant-numeric: tabular-nums; }
.tsl-rate svg { width: ${U(18)}; height: ${U(18)}; fill: none; stroke: var(--acc); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.tsl-rate small { font-size: ${U(11.5)}; color: rgba(236,226,236,.6); }

/* the window */
.tsl-win { position: absolute; z-index: 2; left: 50%; top: var(--wy); width: ${U(932)}; height: ${U(540)}; margin-left: ${U(-466)}; display: flex; padding: ${U(5)};
  border-radius: ${U(14)}; background: #141114; box-shadow: 0 0 0 1px rgba(255,255,255,.1), 0 40px 90px -30px rgba(8,2,10,.7), 0 0 120px -20px rgba(255,190,170,.12);
  translate: calc(var(--px) * ${U(-11)}) calc(var(--py) * ${U(-6)}); color: #18161a; text-align: left; }
.tsl-side { width: ${U(172)}; flex: none; padding: ${U(10)} ${U(10)} 0 ${U(9)}; color: rgba(255,255,255,.78); font-size: ${U(11.5)}; }
.tsl-side-top { display: flex; align-items: center; gap: ${U(7)}; padding: ${U(3)} ${U(3)} ${U(12)}; color: #fff; font-size: ${U(13.5)}; }
.tsl-side-top svg { width: ${U(16)}; height: ${U(16)}; fill: #fff; color: #fff; }
.tsl-side-top b { font-weight: 600; letter-spacing: -.01em; }
.tsl-col { margin-left: auto; width: ${U(11)}; height: ${U(10)}; border: 1px solid rgba(255,255,255,.35); border-radius: ${U(2.5)}; }
.tsl-search { display: flex; align-items: center; gap: ${U(6)}; height: ${U(26)}; padding: 0 ${U(7)}; border-radius: ${U(7)}; background: #fff; color: #9a979c; font-size: ${U(10.5)}; }
.tsl-search svg { width: ${U(11)}; fill: none; stroke: currentColor; stroke-width: 1.5; }
.tsl-search kbd { margin-left: auto; font: 600 ${U(9)} / 1 "Inter Tight", sans-serif; color: #222; }
.tsl-h { display: flex; align-items: center; margin: ${U(16)} 0 ${U(6)} ${U(3)} !important; font-size: ${U(9)}; letter-spacing: .08em; text-transform: uppercase; color: rgba(255,255,255,.38); }
.tsl-plus { margin-left: auto; width: ${U(15)}; height: ${U(15)}; border-radius: 50%; background: #fff; color: #141114; font: 600 ${U(11)} / ${U(15)} "Inter Tight", sans-serif; text-align: center; font-style: normal; }
.tsl-it { display: flex; align-items: center; gap: ${U(8)}; height: ${U(27)}; padding: 0 ${U(6)}; border-radius: ${U(6)}; }
.tsl-it svg { width: ${U(13)}; height: ${U(13)}; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; opacity: .85; }
.tsl-proj i { width: ${U(12)}; height: ${U(12)}; border-radius: ${U(3.5)}; }
.tsl-proj svg { margin-left: auto; width: ${U(11)}; opacity: .5; }
.tsl-on { background: rgba(255,255,255,.08); color: #fff; box-shadow: inset 2px 0 0 #fff; }

.tsl-main { position: relative; flex: 1; border-radius: ${U(10)}; background: #f6f5f4; overflow: hidden; }
.tsl-top { display: flex; align-items: center; height: ${U(38)}; padding: 0 ${U(12)} 0 ${U(14)}; border-bottom: 1px solid rgba(0,0,0,.06); background: #fff; }
.tsl-crumb { font-size: ${U(11)}; color: #9b989d; white-space: nowrap; }
.tsl-crumb i { font-style: normal; margin: 0 ${U(4)}; color: #c4c2c6; }
.tsl-crumb b { color: #19171b; font-weight: 600; }
.tsl-top-r { margin-left: auto; display: flex; align-items: center; gap: ${U(7)}; }
.tsl-ib { display: grid; place-items: center; width: ${U(24)}; height: ${U(24)}; border-radius: ${U(7)}; box-shadow: inset 0 0 0 1px rgba(0,0,0,.08); }
.tsl-ib svg { width: ${U(12)}; fill: none; stroke: #3b393d; stroke-width: 1.3; stroke-linejoin: round; }
.tsl-hist { height: ${U(24)}; padding: 0 ${U(10)}; display: inline-flex; align-items: center; border-radius: 999px; font-size: ${U(10.5)}; font-weight: 500; box-shadow: inset 0 0 0 1px rgba(0,0,0,.1); }
.tsl-me { width: ${U(24)}; height: ${U(24)}; border-radius: 50%; display: grid; place-items: center; background: #2a2630; color: #fff; font-size: ${U(9)}; font-weight: 600; }

.tsl-bar { position: relative; z-index: 3; display: flex; align-items: center; gap: ${U(8)}; height: ${U(42)}; margin: ${U(8)} ${U(8)} 0; padding: 0 ${U(8)} 0 ${U(12)}; border-radius: ${U(9)}; background: #fff;
  box-shadow: 0 0 0 1px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04); white-space: nowrap; }
.tsl-back svg, .tsl-saved svg, .tsl-pub svg { fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.tsl-back svg { width: ${U(13)}; display: block; }
.tsl-name { font-size: ${U(12.5)}; font-weight: 600; letter-spacing: -.01em; }
.tsl-tag { font-size: ${U(8.5)}; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #8d8a90; background: #f1f0ef; padding: ${U(3)} ${U(6)}; border-radius: ${U(4)}; transition: background .3s, color .3s; }
.tsl-live { background: #e3f6ea; color: #16834a; }
.tsl-sp { flex: 1; }
.tsl-saved { display: inline-flex; align-items: center; gap: ${U(5)}; font-size: ${U(11)}; color: #1f9256; transition: color .25s; }
.tsl-saved svg { width: ${U(12)}; }
.tsl-busy { color: #8d8a90; }
.tsl-busy svg { animation: tsl-spin .8s linear infinite; }
@keyframes tsl-spin { to { transform: rotate(360deg); } }
.tsl-avs { display: inline-flex; padding-left: ${U(6)}; }
.tsl-avs i { width: ${U(22)}; height: ${U(22)}; margin-left: ${U(-6)}; border-radius: 50%; display: grid; place-items: center; font: 600 ${U(8)} / 1 "Inter Tight", sans-serif; font-style: normal; color: #1c1a1e; box-shadow: 0 0 0 ${U(2)} #fff; }
.tsl-div { width: 1px; height: ${U(18)}; background: rgba(0,0,0,.1); }
.tsl-draft, .tsl-pub { height: ${U(26)}; padding: 0 ${U(11)}; border: 0; border-radius: ${U(7)}; font-size: ${U(11)} !important; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: ${U(5)}; }
.tsl-draft { background: #fff; color: #19171b !important; box-shadow: inset 0 0 0 1px rgba(0,0,0,.12); }
.tsl-pub { background: #18161a; color: #fff !important; min-width: ${U(70)}; justify-content: center; transition: background .3s, transform .2s cubic-bezier(.3,1.4,.5,1); }
.tsl-pub:active, .tsl-draft:active { transform: scale(.96); }
.tsl-pub-done { background: #1f9256; }
.tsl-pub svg { width: ${U(11)}; stroke-width: 2; }
.tsl-spin { width: ${U(10)}; height: ${U(10)}; border-radius: 50%; border: 1.5px solid rgba(255,255,255,.3); border-top-color: #fff; animation: tsl-spin .7s linear infinite; }

.tsl-canvas { position: absolute; left: 0; right: 0; top: ${U(88)}; bottom: 0; background-color: #f6f5f4;
  background-image: radial-gradient(circle at 1px 1px, rgba(0,0,0,.09) 1px, transparent 1.2px); background-size: ${U(16)} ${U(16)}; }
.tsl-tools, .tsl-zoom { position: absolute; top: ${U(10)}; display: flex; align-items: center; gap: ${U(8)}; height: ${U(24)}; padding: 0 ${U(9)}; border-radius: 999px; background: #fff;
  box-shadow: 0 0 0 1px rgba(0,0,0,.07); font-size: ${U(10.5)}; color: #3b393d; }
.tsl-tools { left: ${U(14)}; } .tsl-tools span + span { opacity: .4; }
.tsl-zoom { left: ${U(470)}; font-variant-numeric: tabular-nums; }
.tsl-plane { position: absolute; left: 0; top: ${U(-14)}; width: ${W(560)}; height: ${W(330)}; }
.tsl-wires { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; z-index: 2; }
.tsl-wire { fill: none; stroke: #d3cfcf; stroke-width: 1.3; }
.tsl-dash { stroke-dasharray: 3 3; }
.tsl-fill { fill: none; stroke: var(--acc); stroke-width: 1.8; stroke-linecap: round; stroke-dasharray: 1 1; }
.tsl-wires g:has(.tsl-fill) { transition: opacity .45s ease; }
.tsl-lab { fill: #f6f5f4; stroke: rgba(0,0,0,.08); stroke-width: .8; }
.tsl-wires text { font: 500 6.6px "Inter Tight", sans-serif; fill: #8d8a90; }
.tsl-token { transition: opacity .18s; }
.tsl-token circle { fill: var(--acc); }
.tsl-token .tsl-halo { opacity: .28; }

.tsl-node { position: absolute; z-index: 1; display: flex; flex-direction: column; align-items: stretch; gap: ${W(5)}; padding: ${W(9)} ${W(10)} ${W(10)}; border: 0; border-radius: ${W(9)}; background: #fff; text-align: left; cursor: pointer;
  box-shadow: 0 0 0 1px rgba(0,0,0,.07), 0 1px 3px rgba(0,0,0,.05); transition: box-shadow .3s ease, transform .3s cubic-bezier(.3,1.4,.5,1); }
.tsl-node:hover { transform: translateY(-1px); }
.tsl-node:active { transform: scale(.98); }
.tsl-nh { display: flex; align-items: center; gap: ${W(7)}; font-size: ${W(11.5)}; color: #18161a; }
.tsl-nh b { font-weight: 600; letter-spacing: -.01em; white-space: nowrap; }
.tsl-gl { flex: none; width: ${W(17)}; height: ${W(17)}; border-radius: ${W(5)}; display: grid; place-items: center; background: #18161a; }
.tsl-gl svg { width: 82%; height: 82%; }
.tsl-k-check .tsl-gl, .tsl-gl.tsl-k-check { background: #f29a3e; border-radius: 50%; }
.tsl-k-branch .tsl-gl, .tsl-gl.tsl-k-branch { background: #6e6ae8; }
.tsl-k-action .tsl-gl, .tsl-gl.tsl-k-action { background: #3f7cf0; }
.tsl-k-stop .tsl-gl, .tsl-gl.tsl-k-stop { background: #e5566b; border-radius: 50%; }
.tsl-k-log .tsl-gl, .tsl-gl.tsl-k-log { background: #8e8a92; }
.tsl-ns { font-size: ${W(10)}; color: #77737a; white-space: nowrap; }
.tsl-chips { display: flex; gap: ${W(4)}; }
.tsl-chips i { font-style: normal; font-size: ${W(8.5)}; color: #77737a; background: #f2f1f0; border-radius: ${W(4)}; padding: ${W(2)} ${W(5)}; }
.tsl-node.tsl-k-stop { flex-direction: row; padding: ${W(7)} ${W(10)}; border-radius: 999px; }
.tsl-k-stop .tsl-gl { width: ${W(14)}; height: ${W(14)}; }
.tsl-k-stop .tsl-nh { font-size: ${W(10.5)}; }
.tsl-k-stop .tsl-nh b { font-weight: 500; }
.tsl-k-log { opacity: .9; }
.tsl-st { margin-left: auto; width: ${W(14)}; height: ${W(14)}; border-radius: 50%; display: grid; place-items: center; background: #1f9256; transform: scale(0); transition: transform .38s cubic-bezier(.3,1.6,.5,1); }
.tsl-st svg { width: 80%; fill: none; stroke: #fff; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.tsl-done .tsl-st { transform: scale(1); }
.tsl-sel { box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--acc) 70%, #fff), 0 4px 14px -6px color-mix(in srgb, var(--acc) 50%, transparent); background: color-mix(in srgb, var(--acc) 5%, #fff); }
.tsl-act { box-shadow: 0 0 0 2px var(--acc), 0 0 0 6px color-mix(in srgb, var(--acc) 18%, transparent), 0 8px 22px -8px color-mix(in srgb, var(--acc) 70%, transparent); }
.tsl-act .tsl-gl { animation: tsl-beat 1s ease-in-out infinite; }
@keyframes tsl-beat { 50% { transform: scale(1.12); } }

.tsl-mate { position: absolute; z-index: 3; display: flex; align-items: flex-start; pointer-events: none; }
.tsl-mate svg { width: ${W(15)}; height: ${W(15)}; fill: #18161a; stroke: #fff; stroke-width: 1.2; stroke-linejoin: round; filter: drop-shadow(0 1px 2px rgba(0,0,0,.25)); }
.tsl-mate span { margin: ${W(11)} 0 0 ${W(-3)}; padding: ${W(3)} ${W(8)} ${W(3)} ${W(7)}; border-radius: 999px; background: #22a462; color: #fff; font-size: ${W(9.5)}; font-weight: 500; white-space: nowrap;
  box-shadow: 0 0 0 ${W(1.5)} #fff, 0 3px 8px -3px rgba(0,0,0,.3); }

.tsl-insp { position: absolute; z-index: 4; right: ${U(10)}; top: ${U(98)}; width: ${U(178)}; padding: ${U(10)}; border-radius: ${U(10)}; background: #fff; box-shadow: 0 0 0 1px rgba(0,0,0,.07), 0 10px 30px -14px rgba(0,0,0,.25);
  font-size: ${U(10.5)}; color: #18161a; }
.tsl-ih { display: flex; align-items: center; gap: ${U(7)}; font-size: ${U(12)}; }
.tsl-ih b { font-weight: 600; letter-spacing: -.01em; }
.tsl-ih .tsl-gl { width: ${U(18)}; height: ${U(18)}; }
.tsl-x { margin-left: auto; color: #9b989d; font-size: ${U(14)}; line-height: 1; }
.tsl-field { display: flex; align-items: center; margin-top: ${U(10)} !important; height: ${U(28)}; padding: 0 ${U(8)}; border-radius: ${U(7)}; box-shadow: inset 0 0 0 1px rgba(0,0,0,.1); color: #3b393d; white-space: nowrap; overflow: hidden; }
.tsl-field svg { margin-left: auto; flex: none; width: ${U(11)}; fill: none; stroke: #9b989d; stroke-width: 1.3; }
.tsl-ilab { display: flex; align-items: center; margin-top: ${U(12)} !important; font-weight: 600; font-size: ${U(11)}; }
.tsl-ilab svg { margin-left: auto; width: ${U(11)}; fill: none; stroke: #77737a; stroke-width: 1.4; }
.tsl-ihint { color: #a29fa5; font-size: ${U(9.5)}; margin-top: ${U(2)} !important; }
.tsl-sel-box { display: flex; align-items: center; gap: ${U(6)}; margin-top: ${U(8)} !important; height: ${U(26)}; padding: 0 ${U(7)}; border-radius: ${U(7)}; box-shadow: inset 0 0 0 1px rgba(0,0,0,.1); font-weight: 500; white-space: nowrap; }
.tsl-yy { display: grid; place-items: center; width: ${U(14)}; height: ${U(14)}; border-radius: ${U(4)}; background: #efeefc; color: #6e6ae8; font-size: ${U(8.5)}; font-weight: 700; }
.tsl-sel-box svg { margin-left: auto; width: ${U(10)}; fill: none; stroke: #77737a; stroke-width: 1.4; }
.tsl-cond { display: flex; align-items: center; gap: ${U(6)}; margin-top: ${U(8)} !important; color: #a29fa5; font-size: ${U(9.5)}; }
.tsl-cond b { color: #1f9256; font-weight: 600; }
.tsl-cond i { width: ${U(7)}; height: ${U(7)}; border-radius: 50%; background: #1f9256; }
.tsl-cond2 b { color: #3b393d; }

/* the near trees, in front of the window */
.tsl-trees { position: absolute; z-index: 3; left: 50%; top: calc(var(--wy) + ${U(-236)}); width: max(109cqw, ${U(1570)}); filter: hue-rotate(-8deg) saturate(.92); translate: calc(-50% + var(--px) * ${U(-46)}) calc(var(--py) * ${U(-18)}); pointer-events: none; }
.tsl-trees img { display: block; width: 100%; height: auto; }
.tsl-floor { position: absolute; z-index: 3; left: 0; right: 0; bottom: 0; height: 30%; pointer-events: none;
  background: linear-gradient(0deg, rgba(16,9,15,.86) 0%, rgba(16,9,15,.5) 38%, transparent 100%); }

/* the bottom line */
.tsl-foot { position: absolute; z-index: 4; left: ${U(40)}; right: ${U(40)}; bottom: ${U(32)}; display: flex; align-items: flex-end; justify-content: space-between; }
.tsl-proof { font-size: ${U(14)}; line-height: 1.3; color: rgba(255,255,255,.9); letter-spacing: -.008em; }
.tsl-stats { list-style: none; display: flex; gap: ${U(36)}; font-size: ${U(13)}; color: rgba(236,226,236,.6); }
.tsl-stats b { color: #fff; font-weight: 500; margin-right: ${U(4)}; font-variant-numeric: tabular-nums; }

/* phone: the headline is sized by the width, the window shows its editor bar and canvas */
@container (max-width: 640px) {
  .tsl-in { --u: calc(100cqw / 390); --w: calc(var(--u) * .74); --wy: ${U(384)}; }
  .tsl-nav { top: ${U(16)}; padding: 0 ${U(16)}; grid-template-columns: 1fr auto; }
  .tsl-logo { font-size: ${U(18)}; }
  .tsl-links, .tsl-login { display: none; }
  .tsl-get { height: ${U(34)}; padding: 0 ${U(14)}; font-size: ${U(13)}; }
  .tsl-menu { display: grid; text-decoration: none; align-content: center; gap: ${U(5)}; width: ${U(34)}; height: ${U(34)}; padding: 0 ${U(10)}; border: 0; border-radius: 50%; background: rgba(255,255,255,.12); cursor: pointer; }
  .tsl-menu i { display: block; height: 1.5px; background: #fff; border-radius: 1px; }
  .tsl-copy { top: ${U(80)}; padding: 0 ${U(16)}; }
  .tsl-pill { height: ${U(28)}; font-size: ${U(11.5)}; padding: 0 ${U(13)}; }
  .tsl-h1 { margin-top: ${U(18)}; font-size: ${U(40)}; line-height: 1; letter-spacing: -.03em; }
  .tsl-sub { margin-top: ${U(14)}; font-size: ${U(14.5)}; max-width: ${U(330)}; }
  .tsl-row { margin-top: ${U(20)}; gap: ${U(18)}; }
  .tsl-cta { height: ${U(44)}; padding: 0 ${U(22)}; font-size: ${U(14.5)} !important; }
  .tsl-rate span { font-size: ${U(15)}; }
  .tsl-rate small { font-size: ${U(10.5)}; }
  .tsl-win { left: ${U(14)}; right: ${U(14)}; width: auto; height: ${U(560)}; margin-left: 0; padding: ${U(4)}; border-radius: ${U(13)}; translate: none; }
  .tsl-side, .tsl-top, .tsl-insp, .tsl-avs, .tsl-div, .tsl-draft, .tsl-zoom { display: none; }
  .tsl-bar { margin: ${U(6)} ${U(6)} 0; height: ${U(38)}; gap: ${U(6)}; padding: 0 ${U(6)} 0 ${U(10)}; }
  .tsl-name { font-size: ${U(12)}; }
  .tsl-saved { font-size: ${U(10.5)}; }
  .tsl-jn { display: none; }
  .tsl-pub { height: ${U(26)}; font-size: ${U(10.5)} !important; min-width: ${U(62)}; padding: 0 ${U(9)}; }
  .tsl-canvas { top: ${U(44)}; }
  .tsl-tools { left: auto; right: ${U(10)}; top: ${U(8)}; }
  .tsl-plane { left: ${U(-8)}; top: ${U(-6)}; }
  .tsl-trees { top: calc(var(--wy) + ${U(-110)}); width: ${U(980)}; translate: -50% 0; }
  .tsl-floor { height: 22%; }
  .tsl-foot { left: ${U(16)}; right: ${U(16)}; bottom: ${U(22)}; justify-content: center; }
  .tsl-proof { text-align: center; font-size: ${U(13)}; }
  .tsl-stats { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .tsl-sky, .tsl-win, .tsl-trees { translate: none; }
  .tsl-trees { translate: -50% 0; }
  .tsl-act .tsl-gl, .tsl-busy svg, .tsl-spin { animation: none !important; }
  .tsl-node, .tsl-st { transition: none; }
}
`;
