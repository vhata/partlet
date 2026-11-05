# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Needs proof of concept

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Waiting

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [SITE] `vendored-site-themes` — **Support reviewed third-party theme distributions selected from the source repository.** Versioned CSS and explicitly declared raster assets let publishers install a theme without a Partlet fork or executable plugin.
  - Source: user theming request, branch vhata/partlet-site-theming, 2026-11-04
  - Starting point: [Site themes design](docs/specs/2026-11-04-site-themes.md), theme contract and publication sections.
  - Depends on: `bundled-site-themes`
  - Acceptance: committed, snapshotted inputs; strict paths and asset allowlists; format compatibility; installed CLI/Action parity; immutable asset routes and retention; a working example pack and author/install guide; independent review and appropriate local checks.

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [SITE] `bundled-site-themes` — **Offer Classic, Paper and Terminal site themes with automatic, light and dark modes.** A documented CSS contract and versioned resources make theme changes reproducible across the browser, publisher and Action.
  - Source: user theming request, branch vhata/partlet-site-theming, 2026-11-04
  - Starting point: [Site themes design](docs/specs/2026-11-04-site-themes.md); manifest parsing, site rendering, build identity and Worker stylesheet routing.
  - Acceptance: default compatibility; coherent code colors; theme-only rebuilds without Git history changes; upload-before-reference and legacy CSS handling; safe index regeneration during unpublish; installed package coverage; documented selection/discovery; light/dark and narrow-screen visual evidence; independent review and appropriate local checks.
