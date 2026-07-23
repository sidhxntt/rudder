# Phase 6 — Deploy advisor

**Target:** 1–2 weeks

**Demo:** point at a connected repo, get a proposed service graph rendered as
ghost nodes on the canvas. Accept per item.

**This is the only place in the system where an LLM belongs. It proposes; it
never applies.**

That constraint is not a style preference. Everything else in Rudder is
deterministic — language detection, scheduling, reconciliation, routing. An LLM
that could mutate state would make the platform's behavior unreproducible.

---

## Prerequisites

- [ ] Phase 1 verified (needs the service graph and canvas)
- [ ] `ANTHROPIC_API_KEY` in `.env` — see `../NEED-FROM-YOU.md` item 12

---

## Steps

### 1. Repo scan

Static analysis, not model calls. This part is deterministic and testable.

| Look for | Propose |
|---|---|
| Web framework entrypoint — Express, FastAPI, Django, Gin | app service with a public domain |
| Queue consumers — Celery, BullMQ, a `worker.py` | worker service, **no public domain** |
| Imports of `psycopg2` / `asyncpg` | Postgres backing service + `DATABASE_URL` wiring |
| Imports of `redis` | Redis backing service + `REDIS_URL` wiring |
| Imports of `boto3` | flag it — S3 is external, needs credentials from the user |
| Web handler routes | health check path, **preferring one that does not touch the database** |
| Language + dependency weight | memory limit proposal |

That health-check preference matters: a health check that queries the database
will fail the whole service during a database blip, taking down something that
was otherwise fine.

### 2. Diff against the current graph

Output is a **diff**, not a graph. What's new, what changes, what's unaffected.

Rendered on the canvas as **ghost nodes** — visually distinct, clearly not real
yet.

### 3. Per-item accept

Each proposed service, variable, and health check is accepted or rejected
individually. Accepting one does not accept the rest.

**Nothing is applied automatically.** There is no "accept all and deploy" path.

### 4. Failure diagnosis

Second feature, separate from the graph advisor.

On build or deploy failure: send the last 100 log lines plus the service config
to the model, return a plain-language diagnosis.

**Display it alongside the raw log, never instead of it.** The raw log is the
ground truth; the diagnosis is a convenience that can be wrong.

Mark it visually as model-generated. Users must never mistake a guess for a fact.

---

## Where this goes wrong

**Scope creep into "just let it apply the safe ones."** There is no safe subset.
The moment the model can mutate state, every deploy becomes non-reproducible and
every debugging session starts with "did the advisor change something." Hold the
line.

**Diagnosis replacing the log.** Same failure mode, softer. If the UI shows the
diagnosis prominently and the log behind a toggle, people will stop reading logs
and start debugging the model's guesses.

**Static analysis dressed up as AI.** Steps 1 and 2 are deterministic scanning
and should be tested as such — same repo in, same proposal out, every time. Only
the *phrasing* of the failure diagnosis should be non-deterministic. Do not route
the repo scan through the model; it will be slower, more expensive, and less
reliable than grep.

**Prompt injection from repo contents.** The advisor reads untrusted repository
files. A repo containing text shaped like instructions must not change what the
advisor does. Treat all file content as data. Since the advisor cannot apply
anything, the blast radius is a bad suggestion — which is the reason the
propose-only rule pays for itself.

**Cost per scan.** A large repo's worth of context on every scan adds up. Scan
deterministically, send only the summary to the model.

---

## Verify

```bash
# 1. Deterministic scan
rudder advise <repo> --json > a.json
rudder advise <repo> --json > b.json
diff a.json b.json                  # → identical. Every time.

# 2. Proposals are sensible on a known repo
#    a Django + Celery + Postgres + Redis repo should propose
#    exactly: 1 app, 1 worker (no domain), postgres, redis, and the wiring

# 3. Nothing applies without acceptance
rudder advise <repo>
rudder service list                   # → unchanged
# accept one item on the canvas
rudder service list                   # → exactly that one item, nothing else

# 4. Health check avoids the database
#    repo with GET /health (db query) and GET /ping (no db)
# → proposes /ping

# 5. Failure diagnosis shows alongside the log
#    force a build failure
# → UI shows raw log AND diagnosis, diagnosis clearly marked as generated

# 6. Prompt injection
#    add a repo file containing instruction-shaped text
# → proposal unchanged, no behavior change
```

---

## Done when

- [ ] Scan output is byte-identical across repeated runs on the same commit
- [ ] Django + Celery + Postgres + Redis repo produces the correct graph
- [ ] Worker services are proposed with no public domain
- [ ] Health check proposal prefers a non-database endpoint
- [ ] Ghost nodes are visually distinct from real services
- [ ] Per-item accept works; nothing applies without it
- [ ] Failure diagnosis appears alongside the raw log, marked as generated
- [ ] Instruction-shaped text in a repo does not change advisor behavior
- [ ] No code path exists where the model mutates state
- [ ] `README.md` Phase 6 section
