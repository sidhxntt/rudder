---
name: Rudder
description: A dark, self-hosted deployment workspace for visible service operations.
colors:
  accent: "#3ecf8e"
  accent-deep: "#24b47e"
  accent-soft: "#4ade80"
  surface: "#1c1c1c"
  surface-raised: "#242424"
  surface-inset: "#171717"
  hairline: "#2e2e2e"
  ink: "#ededed"
  ink-secondary: "#b2b2b2"
  ink-muted: "#9a9a9a"
  status-building: "#ffdb13"
  status-failed: "#ff2201"
typography:
  display:
    fontFamily: 'Inter, "Helvetica Neue", Helvetica, Arial, sans-serif'
    fontSize: "clamp(3rem, 7vw, 6.25rem)"
    fontWeight: 500
    lineHeight: 0.91
    letterSpacing: "-0.055em"
  body:
    fontFamily: 'Inter, "Helvetica Neue", Helvetica, Arial, sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: 'ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace'
    fontSize: "12px"
    lineHeight: 1.45
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
spacing:
  xxs: "2px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
  huge: "64px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#171717"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.accent-deep}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "44px"
---

# Design System: Rudder

## Overview

**Creative North Star: "The Visible Control Plane"**

Rudder is a dark operational surface: quiet in its foundations, explicit when a release is alive, building, or failing. The public landing page expands that established console into a persuasive narrative without changing its product truth. Architecture is shown as precise service geometry, not decorative illustration.

**Key Characteristics:**
- Dense, near-black operator surfaces with one emerald action/status accent.
- Large, low-tracking display type set against compact operational labels.
- Hairlines and tonal layers carry structure; diagrams carry the product proof.

## Colors

The palette is a charcoal workspace interrupted only by actionable emerald and semantic state colors.

### Primary
- **Release Emerald:** the sole non-semantic accent for primary action, successful live state, and deliberate focus.

### Neutral
- **Canvas Night:** the outer application and marketing ground.
- **Raised Graphite:** panels, nodes, and popovers separated through tonal lift.
- **Inset Black:** logs and code surfaces that read as deeper runtime context.
- **Operator Ink:** high-contrast text with a stepped secondary/muted hierarchy.

### Named Rules
**The One Accent Rule.** Emerald is reserved for action, success, and the active release path; it is never used as generic decoration.

## Typography

**Display Font:** Inter, with Helvetica Neue/Helvetica/Arial fallbacks.
**Body Font:** Inter, with Helvetica Neue/Helvetica/Arial fallbacks.
**Label/Mono Font:** ui-monospace, Menlo, Monaco, Consolas, Liberation Mono.

**Character:** Display copy is compact and calm; monospace identifies commits, ports, code, and measured operational state rather than simulating technicality.

### Hierarchy
- **Display** (500, responsive 3rem–6.25rem, tight line-height): the landing-page thesis.
- **Headline** (500, 22–28px): section-level product statements.
- **Body** (400, 16px, 1.5): explanatory product copy, held to a readable measure.
- **Label** (12–13px, often uppercase/tracked or mono): status, release, and supporting metadata.

### Named Rules
**The Evidence Rule.** Monospace appears only where the interface is naming code, a commit, a port, a command, or a measured state.

## Layout

Console routes stay dense and panel-oriented. Persuasive routes use a centered `max-w-7xl` frame, 20–40px responsive side gutters, and generous 96–128px vertical breaks between major arguments. The landing hero becomes a two-column product proof at large widths and stacks copy before the service graph on smaller screens.

## Elevation & Depth

Depth comes primarily from a tonal charcoal ladder and one restrained soft black elevation under featured surfaces. Borders are functional hairlines, not card decoration. The service graph gets its atmosphere from a dotted coordinate field and illuminated release path, not frosted glass.

### Shadow Vocabulary
- **Operator lift** (`0 24px 80px rgba(0,0,0,0.35)`): reserved for the landing service-graph proof.
- **Console elevations** (`0 1px 3px`, `0 8px 24px`, `0 16px 48px` with black alpha): used by existing panels and popovers.

## Shapes

Rudder uses disciplined, lightly rounded forms: small 4–8px radii for controls and field boundaries, 12–16px only for major featured surfaces. Pills are limited to tiny status/control elements; cards do not become generic rounded containers.

## Components

### Buttons
- **Shape:** compact rectangular control with a 6px radius.
- **Primary:** emerald fill with near-black text; 44px minimum height on public actions.
- **Hover / Focus:** darker emerald or brighter border, a one-pixel focus ring, and a small upward motion only for prominent public CTAs.
- **Secondary:** transparent surface with a strong hairline; it never competes chromatically with the primary action.

### Inputs / Fields
- **Style:** inset charcoal background, strong hairline, 6px radius, and mono text for key/value configuration.
- **Focus:** emerald border and restrained low-opacity ring.

### Navigation
- **Style:** minimal text links, compact height, and no decorative container. The brand mark stays an operational signal, not a home-page button inside the console.

### Service Graph
- **Style:** thin directional paths, readable service nodes, and real labels such as ports, private network roles, and release state.
- **State:** the active release path may glow emerald; private services remain neutral until selected or unhealthy.

## Do's and Don'ts

### Do:
- **Do** show the system doing real work—service topology, release state, commands, logs, and routes are Rudder's strongest proof.
- **Do** use charcoal tonal layers and 1px hairlines to establish containment before adding shadow.
- **Do** respect `prefers-reduced-motion` when adding movement to release or topology visuals.

### Don't:
- **Don't** use invented benchmarks, customer logos, price comparisons, or claims of AWS/Azure availability.
- **Don't** turn the green accent into a decorative gradient, a generic success wash, or a second visual language.
- **Don't** replace operational diagrams with icon-card grids or faux dashboards.
