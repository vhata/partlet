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

- [WORKER] `worker-plan` — **Write the implementation plan for the Cloudflare Worker.** Plan 2 of 3 from the design spec; written once the publisher core shows what the stored layout looks like in practice.
  - Source: plans/2026-10-15-publisher-core.md, 2026-10-15
  - Depends on: `publisher-core`
- [ACTION] `r2-publishing-plan` — **Write the implementation plan for publishing to R2.** Plan 3 of 3: R2 store, gitleaks, `partlet review`, `publish` and `unpublish`, the composite action and the end-to-end test.
  - Source: plans/2026-10-15-publisher-core.md, 2026-10-15
  - Depends on: `publisher-core`

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [PUBLISHER] `publisher-core` — **Implement the publisher core plan, ending in a working `partlet build`.** First buildable slice of the design; everything else builds on its storage layout.
  - Source: plans/2026-10-15-publisher-core.md, 2026-10-15
  - Starting point: Task 1 of plans/2026-10-15-publisher-core.md
