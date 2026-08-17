# ADR 0002 — The project is named Rudder, not Helm

**Date:** 2026-07-23
**Status:** Accepted

## Context

The project was drafted as "Helm". `helm` is the Kubernetes package manager: a
binary most people building container infrastructure already have on `$PATH`, and
a term that pollutes every search run while building this. A CLI named `helm`
would shadow or be shadowed by it.

Renaming after the scaffold hardcodes the name is a mechanical but wide change —
Python package name, env var prefix, CLI entrypoint, docs.

## Decision

The project is **Rudder**.

| Thing | Value |
|---|---|
| Control plane package | `rudder_cp` |
| Agent package | `rudder_agent` |
| CLI binary | `rudder` |
| Env var prefix | `RUDDER_` |
| Docker network | `rudder` |
| Compose project | `rudder` |

`GITHUB_TOKEN` and `OPENAI_API_KEY` keep their conventional names — they are
not Rudder's namespace.

## Rejected alternatives

- **Keep Helm.** Zero doc churn, but a live PATH collision with a tool in the
  same domain, and permanently degraded search.
- **Pier.** No collision, dock metaphor. Rejected in favour of Rudder on taste.
