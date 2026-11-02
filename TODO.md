# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [PUBLISHER] `fetch-retention-window` — **Keep advertised objects live.**
  Define a fetch window across rapid publications. One publication of
  grace can expire inside the Worker's 60-second metadata cache window.
  - Source: task/worker-delivery, 2026-11-02
  - Starting point: `src/partlet/publish.py:_sweep`,
    `worker/test/adversarial.test.ts`, `worker/README.md` retention limit.
  - Evidence: cached A refs/pack list, followed by B and C consolidation,
    can name a deleted A pack; the Worker returns an uncached 404.
    Disabling metadata caching alone does not protect an in-flight fetch.
  - Decide a retention duration covering metadata age plus fetch duration
    or an equivalent publication snapshot protocol; test rapid publishes,
    abandoned uploads, retries and unpublication with synthetic objects.

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
