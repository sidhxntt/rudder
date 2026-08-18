# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Solo developers who want to deploy applications from repositories without giving up visibility into services, releases, and runtime operations.

## Product Purpose

Rudder is a self-hosted deployment workspace. It turns a GitHub repository or Compose graph into a running application and its private dependencies, then exposes the delivery and operational state through a canvas and Node/TypeScript CLI.

## Positioning

Rudder combines a Compose-derived service graph with immutable releases and operator-facing control. It is not a multi-tenant hosted PaaS.

## Operating Context

Developers sign in through GitHub, import a repository, inspect the resolved release, deploy locally with Docker or Kind, and can use a controlled-beta GKE target. They use build logs, runtime logs, analytics, environments, operations, and immutable restore while shipping.

## Capabilities and Constraints

- GitHub OAuth and GitHub App repository import are supported.
- Docker Compose, Kind, and Git-based deployments are supported locally.
- GKE is verified for a shared-pool controlled beta; it is not represented as general availability.
- AWS/EKS and Azure/AKS are planned provider adapters, not current capabilities.
- The current product is single-tenant by design.
- Vite, CRA, Astro static, and Next static export are supported frontend paths; Next SSR is an application container.

## Brand Commitments

Rudder uses a dark, operator-grade visual language with a restrained green status accent. Product claims must be documented and verifiable; do not fabricate customer stories, benchmarks, or cloud availability.

## Evidence on Hand

- Product truth: `README.md`, `docs/index.md`, and `docs/phases/`.
- Verified GKE controlled-beta evidence: `docs/evidence/phase-4-controlled-beta.md`.
- Existing console design tokens: `web/styles/tokens.css`.
- No customer testimonials, external reviews, commercial metrics, or brand assets are available for the landing page.

## Product Principles

1. Show the deployment system, not just a deploy button.
2. Make delivery state observable and recoverable.
3. Keep private dependencies private by default.
4. Preserve developer control without inventing platform certainty.

## Accessibility & Inclusion

The public site must use semantic HTML, keyboard-operable controls, sufficient contrast, and reduced-motion behavior.
