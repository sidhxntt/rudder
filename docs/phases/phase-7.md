# Phase 7: frontend delivery and permanent release URLs

> **Status:** implemented and covered in focused control-plane/dashboard tests. A two-release live static-site exercise remains the strongest delivery proof.

## Problem and plan

Web projects need different build and cache behavior than a generic server container, but they must retain Rudder’s immutable-release and rollback semantics. Phase 7 added framework-aware frontend presets, deployment-pinned URLs, and dashboard visibility without introducing a second preview lifecycle.

## Design

Dockerfile precedence is absolute: an explicit repository Dockerfile remains user-owned. Without one, detection classifies Vite, CRA, static Next export, Astro static, or Next SSR from dependency/configuration evidence. Static projects use a multi-stage build and a non-root nginx runtime; SSR Next remains an ordinary app container.

The preset knows output directory, SPA fallback, and permitted public build-variable prefix:

| Preset | output/runtime | fallback | build variables |
| --- | --- | --- | --- |
| Vite | `dist`, nginx | yes | `VITE_*` |
| CRA | `build`, nginx | yes | `REACT_APP_*` |
| static Next | `out`, nginx | no | `NEXT_PUBLIC_*` |
| Astro static | `dist`, nginx | no | `PUBLIC_*` |
| Next SSR | normal Node app | n/a | app contract |

Build variables are allowlisted from `build_config.build_env`, passed as build args, and never printed as runtime environment or build logs. Changing one requires a new immutable deployment.

Every healthy release receives a permanent deployment domain, `d-<deployment-prefix>.<base-domain>`, targeting that Deployment. The service’s normal system domain is the mutable live alias. Promotion/restore changes only the alias; permanent URLs remain stable. Kubernetes creates release-qualified routing so the permanent URL survives later promotions, while route changes use compensation/ordering protections to avoid partial promotion.

## Why this is not another PR-preview feature

A permanent URL is a code/release artifact. Phase 5 PR environments are full copied graphs with isolated backing services and a cleanup lifecycle. Keeping them separate avoids a branch URL accidentally sharing production data or duplicate cleanup semantics.

## Challenges, cloud impact, and cost

Static assets benefit from immutable cache headers but `index.html` must remain fresh; nginx policy handles this distinction. Each permanent public URL implies DNS/Ingress/certificate objects and consumes operational attention; they must therefore be tied to deployment lifecycle, not an uncontrolled arbitrary domain mechanism. On GKE, the shared ingress controller and delegated Cloud DNS zone make this portable, but certificate issuance/DNS propagation remain external dependencies. Build caching, image-registry storage, and retained old releases are the principal cost tradeoff for reliable rollback.

## Verification and limits

Coverage verifies detection/templates, output selection, safe build-env filtering, URL/domain creation, and dashboard history. A live check should deploy two static releases, verify both permanent URLs answer, restore the first service alias without a rebuild, and confirm client-side routing only for SPA presets. The canonical requirements are summarized here.
