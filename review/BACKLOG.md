# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [SITE] `local-store-path-identity` — **Prevent local path aliases.** A
  successful local build must not silently serve another file's bytes
  when names differ by case or Unicode normalization.
  - Source: `review/2026-10-27-1621-full.md`, 2026-10-27
  - Starting point: `src/partlet/store.py` and publication preflight;
    reproduce distinct Git-index paths on a case-insensitive filesystem
    and compare raw/blob keys with byte-safe export entries.
  - Findings: `local-store-filesystem-path-alias`

- [PUBLISHER] `local-store-list-committed-temp-names` — **List all content.**
  Files named `.partlet-tmp-*` escape the store listing and remain
  physically present after their site's grace generation expires.
  - Source: `review/2026-10-27-1621-full.md`, 2026-10-27
  - Starting point: `LocalStore.list` and its temporary-file namespace;
    publish `.partlet-tmp-keep`, advance twice, and verify retired raw and
    blob objects are physically removed while live/grace objects remain.
  - Findings: `local-store-temp-prefix-hides-content`
