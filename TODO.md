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

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [ACTION] `r2-publishing-plan` — **Write the implementation plan for publishing to R2.** Plan 3 of 3: R2 store, gitleaks, `partlet review`, `publish` and `unpublish`, the composite action and the end-to-end test.
  - Source: plans/2026-10-15-publisher-core.md, 2026-10-15
  - The export needs a local `refs/heads/<branch>` in the monorepo checkout and fails with "branch ... not found" without one; the action's checkout step must provide it.
  - The test sandbox in `tests/conftest.py` must also strip R2 and Cloudflare credential variables, so no test can reach a real bucket; the R2 store's tests run against a local or fake endpoint only.
- [PUBLISHER] `publish-orphan-sweep` — **Delete keys left behind by an interrupted publish.** Packs, site builds and archives uploaded by a publish that dies before writing `cleanup.json` are listed nowhere, so the next publish never removes them, although the design spec promises it does.
  - Source: todo/publisher-core, 2026-10-15
  - A crash after the pointers and `current` move but before `cleanup.json` is written also loses the superseded keys, and the next run then takes the `unchanged` shortcut.
  - Any sweep must keep the previous build, archives and superseded packs for one publish of grace (see `docs/DECISIONS.md`). Cleanup skips keys that are live (current build, current archives, listed packs), so an interrupted publish cannot delete live data; the cost is leaked storage, which matters most once the R2 store lands.
