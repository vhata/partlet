# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [TOOLING] `publisher-credential-bootstrap` — **Design optional API creation of bucket-scoped publisher credentials and transfer to GitHub secrets.** Cloudflare supports token creation through its API, but requires a separate dashboard-created bootstrap token with token-management permission; decide whether the benefit for repeated installations justifies that authority and recovery complexity.
  - Source: Cloudflare setup automation request, branch vhata/cloudflare-dashboard-automation, 2026-11-05
  - Starting point: docs/GETTING_STARTED.md credential step; https://developers.cloudflare.com/r2/api/tokens/ and https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/. Keep the bootstrap token out of files and logs; scope generated credentials to one bucket, transfer secrets over stdin, and define recovery for unknown token-creation or partial GitHub-secret updates before implementation.

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

- [SITE] `semantic-site-markup` — **Design semantic HTML and rebuild themes around a new versioned output contract.** Give themes access to timestamps, complete exported revisions, byte counts, and entry kinds without constraints from the old tables, CSS hooks, or theme format.
  - Source: site structure and sophisticated themes discussion, branch vhata/site-structure-theming-review, 2026-11-05
  - Starting point: [semantic site design](docs/specs/2026-11-05-semantic-site.md) and [implementation plan](plans/2026-11-05-semantic-site.md), step 2; site templates, base theme CSS, and publisher build identity.
  - Acceptance: ship semantic output version 1 and redesigned format-2 themes with accessible structure, documented hooks, and renderer revision in build identity. Replace obsolete markup, tokens, packs, and presentation routes coherently; no format-1 adapters, old index JSON shape, or legacy-page support are required. Keep repository content inert, source-free index/unpublish rebuilding functional, and resources referenced by live pages available after partial failures. Verify all page/content kinds, every shipped theme and custom example in both modes and narrow layouts, preview/package parity, repository checks, and independent review. Custom templates, JavaScript, and new page-data APIs are excluded.
