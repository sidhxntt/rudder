# What I Need From You

Everything blocking or gating work, in the order it becomes needed. Nothing here
is something I can decide or provision myself.

Legend: **BLOCKING** — work stops. **GATING** — work proceeds, that phase cannot
be verified. **HEADS-UP** — plan ahead, not needed yet.

---

## Resolved 2026-07-23

Items 1–3 are done. Kept below for the record.

- **Decisions** — all seven accepted as defaults. [ADR 0001](decisions/0001-phase-1-decisions.md).
- **Repo root** — `/Users/siddhantinvytt/Desktop/Code/Railway Clone/`, `git init` run, scaffold built around the existing `docs/`.
- **Name** — Rudder. [ADR 0002](decisions/0002-project-name-rudder.md).

**Still blocking: items 4–8 below, before Phase 1 step 5.**

---

## Right now — BLOCKING Phase 1

### 1. Seven decisions

Full reasoning in `PRD.md` → "Open Decisions". Short form:

| # | Question | My default |
|---|---|---|
| D1 | Service needs `container_port` separate from `health_check_port`? | Yes, add it, default 8080 |
| D2 | GitHub auth for cloning private repos | Single `GITHUB_TOKEN` env var, no per-repo model in Phase 1 |
| D3 | Build the node agent in Phase 1 or Phase 2? | Phase 1, on localhost. ~4 days now, saves ~1 week later |
| D4 | Does "logs" in the Phase 1 UI mean build logs only? | Yes. Runtime logs are Phase 5 |
| D5 | `web/` design system | Take DESIGN-supabase.md token scales, invert surfaces to dark |
| D6 | Truth ownership: DB or code | DB. `canvas_x/y` is UI-only metadata |
| D15 | Route on Service or on a first-class Domain? | Domain, added in Phase 1 |

**Reply `defaults` to accept all seven as written.** Otherwise answer per line.

D7–D14 are silent defaults I will take unless you object — see the same section.

Of these, **D3 is the one with a real cost either way** and **D5 needs your
taste, not my judgment.**

### 2. Confirm the repo root

Is `/Users/siddhantinvytt/Desktop/Code/Railway Clone/` the repo root, with `docs/`
already in place? If so I will `git init` here and scaffold around the existing
`docs/`. Say if you want a different layout.

### 3. Project name

`Rudder` collides with the Kubernetes package manager. Every search you run while
building this will be polluted, and anyone you show it to will be confused. Worth
30 seconds now. Keep it or rename — either is fine, but decide before the
scaffold hardcodes it into module names (`rudder_cp`, `rudder` CLI, `RUDDER_*` env
vars).

---

## Before Phase 1 step 5 (build pipeline) — BLOCKING

### 4. GitHub personal access token

Scope: `repo` (read). Used to clone private repos.

Put it in `.env` as `GITHUB_TOKEN=`. Do not paste it into chat — write it to the
file yourself and tell me it's there.

If every repo you deploy is public, say so and I will skip the auth path
entirely in Phase 1.

### 5. A test repo, or permission to use public ones

I need at least two real repos to verify against — one Node, one Python. Either:
- Point me at two of yours, or
- I use two small public repos and you confirm that's fine.

### 6. Webhook tunnel

GitHub cannot reach `localhost`. Pick one:
- **ngrok** — `ngrok http 8000`, free tier, URL changes on restart
- **cloudflared** — `cloudflared tunnel --url http://localhost:8000`, free, same caveat
- **A public dev box** — stable, more setup

You install and authenticate it; I cannot. Tell me which and I will wire the
webhook registration around it.

### 7. One-time Docker daemon change — NOT NEEDED on Docker 29

Verified 2026-07-23 on Docker 29.6.1: `127.0.0.0/8` is already in the daemon's
insecure-registry CIDRs by default, so `localhost:5000` works with no change.
A full build/push/pull cycle succeeded without touching Docker Engine settings.

Still required on older daemons, or if you move the registry off localhost.
Original instructions below.



The local registry runs insecure (no TLS). Your Docker daemon must be told to
trust it:

Docker Desktop → Settings → Docker Engine → add:

```json
{
  "insecure-registries": ["localhost:5000"]
}
```

Then Apply & Restart.

This is the one documented exception to the "no manual steps" rule in the
Definition of Done. Without it, every image pull fails with a TLS error that
looks unrelated.

---

## Before Phase 1 step 8 (routing) — GATING

### 8. Domain strategy

Two modes, and you need to pick before ACME config is written:

- **Dev only (recommended to start).** `RUDDER_TLS_MODE=off`, hostnames are
  `{service}.{env}.localhost`. Nothing to buy. Works today.
- **Real TLS.** Needs a domain you own, a wildcard `*.rudder.yourdomain.com` A
  record pointed at the host, and port 80 reachable from the public internet for
  Let's Encrypt HTTP-01.

If real TLS: I need the base domain and an email address for the ACME account.

Starting in dev mode and switching later costs nothing — it's an env var.

---

## Before Phase 2 (multi-host) — BLOCKING that phase

### 9. Two or more Linux hosts with root

Needed only for the Phase 2 Docker multi-host lab. **macOS cannot run node agents
natively** — the agent drives a Linux Docker daemon with host networking access.
Phase 3 onward does not need these hosts: Kind runs locally and Phase 4 runs on
GKE nodes Google manages.

Options, cheapest first:
- **Local VMs** — Multipass or UTM, 2 Ubuntu VMs, 2GB RAM each. Free. Slow on a
  laptop but fine for correctness testing.
- **Cloud** — 2× Hetzner CX22 (~€4/mo each) or 2× DigitalOcean basic ($6/mo
  each). Real network conditions, which matters for Phase 3.
- **Spare hardware** — old laptops, Raspberry Pi 4s.

Local VMs are enough — the Phase 2 lab only needs two reachable Linux Docker
hosts. (Resolved 2026-07-29: this was satisfied with GCP VMs, which stay a
scheduler testbed and are **not** the Phase 4 production node pool.)

Needed: hostnames/IPs and SSH access.

### 10. Budget confirmation

If cloud: ~€8–12/month for two nodes. Confirm you're okay with that before I
write anything that assumes it.

---

## Before Phase 4 (GKE landing zone)

WireGuard is cancelled ([ADR 0004](decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md)),
so the old "open UDP 51820 / install `wireguard-tools`" ask is void.

### 11. GCP project, billing, and IAM — RESOLVED 2026-07-29

Audited on `invytt-2483d`: billing enabled (`01284A-2DDEFC-61E5C6`), operator
account `siddhant@invytt.com` holds `roles/owner`, region default already
`asia-south1`, ADC present. No IAM grants were needed.

Actions taken: enabled the five missing APIs (container, artifactregistry, dns,
certificatemanager, secretmanager); installed Terraform 1.15.8 and
`gke-gcloud-auth-plugin` locally. All ten Phase 4 APIs are now enabled. No cloud
resources were created.

Inventory found: no clusters, no DNS zones, no Artifact Registry repositories, and
a leftover `rudder-vpc` custom-mode VPC from Phase 2.

### 12. Architecture decisions — RESOLVED 2026-07-29

Recorded in [ADR 0005](decisions/0005-phase-4-kubernetes-only-attach-mode.md):
Kubernetes-only in production, **attach mode**, **CloudNativePG** for Postgres,
ingress-nginx + cert-manager for the edge, and public hostnames under
`rudder.invytt.com`.

### 13. Still needed before the first `terraform apply` — BLOCKING

1. **Budget confirmation.** Under K8s-only there is no Cloud SQL line item.
   A regional private GKE Standard cluster with a small customer node pool, one
   load balancer, persistent disks, and Artifact Registry storage runs roughly
   **$150–300/month** — in-cluster Postgres needs more node and disk capacity than
   the Cloud SQL variant, which is where part of the Cloud SQL saving goes back.
   Confirm before I provision anything.
2. **GoDaddy DNS access.** After I create the Cloud DNS zone I will give you four
   NS records to add for the `rudder` subdomain of `invytt.com`. I cannot do this
   — GoDaddy holds that zone. The apex and your existing records are untouched.
3. **`rudder-vpc` call.** Reuse the Phase 2 VPC or build a purpose-made
   `rudder-gke-vpc`? It has no secondary ranges for Pods and Services, which a
   VPC-native cluster requires. My recommendation is a new VPC; reusing it means
   grafting cluster ranges onto lab networking.
4. **An acceptance repository.** Phase 4's verification needs a private GitHub
   repo containing `app`, `worker`, `postgres`, and `redis`. Point me at one or
   confirm I should create it.

### 14. Verification you have to do yourself — GATING

Phase 4's acceptance run includes "from outside the cluster, confirm Postgres is
unreachable" and "kill a node, confirm the public URL stays up." I can script most
of it; some needs you to look at a screen and confirm.

---

## Before Phase 7 (advisor) — GATING

### 15. An Anthropic API key

Only used in Phase 7. Nowhere else in the system touches an LLM — that's an
explicit rule in the PRD.

`ANTHROPIC_API_KEY=` in `.env`. Same rule: write it yourself, don't paste it.

---

## Ongoing — what I need from you during the build

**Per the Working Agreement, I stop and ask before writing code for each task.**
What that means practically:

- **Decisions, not implementations.** When the spec is ambiguous I will ask
  rather than invent. Answering "your call" is a valid answer and I'll take the
  default.
- **Verification I cannot do myself.** Several phases end in "kill the container
  manually and confirm the UI reflects it" or "confirm staging cannot reach
  production." Some of that I can script; some needs you to look at a screen.
- **Design taste.** D5 and the canvas UI generally. I can build to a spec; I
  can't tell you which of two layouts you'd rather use every day.
- **Scope pushback.** If I propose something that smells like the speculative
  abstraction the PRD bans, say so. That rule is easy to violate by accident.

---

## Summary — the shortest path to unblocking me

1. Reply `defaults` (or answer D1–D6, D15)
2. Confirm repo root and whether the name stays `Rudder`
3. Write `GITHUB_TOKEN` into `.env`
4. Add `localhost:5000` to Docker insecure-registries
5. Install ngrok or cloudflared, tell me which
6. Say `dev` or give me a domain + ACME email

That's enough for all of Phase 1. Items 9–10 gated Phase 2 and are resolved.
Items 11 and 12 are resolved as of 2026-07-29. **Item 13 is what now blocks
Phase 4** — budget confirmation, GoDaddy NS records, the `rudder-vpc` call, and an
acceptance repository. Item 15 waits until Phase 7.
