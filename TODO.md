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

- [SITE] `semantic-site-markup` — **Publish semantic HTML with raw values and stable theme hooks.** Give future themes access to timestamps, complete exported revisions, byte counts, and entry kinds while preserving usable static pages and the existing CSS theme contract.
  - Source: site structure and sophisticated themes discussion, branch vhata/site-structure-theming-review, 2026-11-05
  - Depends on: `site-page-models`
  - Starting point: [semantic site design](docs/specs/2026-11-05-semantic-site.md) and [implementation plan](plans/2026-11-05-semantic-site.md), step 2; site templates, base theme CSS, and publisher build identity.
  - Acceptance: implement the documented semantic elements and attributes, accessible table/breadcrumb structure, and renderer revision in build identity. Preserve format-1 hooks, index JSON, CSP, and source-free index/unpublish rebuilding. Verify renderer-only regeneration, parsed HTML across all page/content kinds, and browser appearance for bundled themes and Copper in both modes and narrow layouts; complete repository checks and independent review. Custom templates, JavaScript, and new JSON routes are excluded.

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [SITE] `site-page-models` — **Define versioned page models that retain original public values independently of HTML layout.** Replace positional renderer inputs with named records so templates and future consumers can use complete exported revisions, precise timestamps, byte counts, entry kinds, and generated public URLs without parsing display strings or exposing publisher internals.
  - Source: site structure and sophisticated themes discussion, branch vhata/site-structure-theming-review, 2026-11-05
  - Starting point: [semantic site design](docs/specs/2026-11-05-semantic-site.md) and [implementation plan](plans/2026-11-05-semantic-site.md), step 1; src/partlet/site/render.py, tree.py, urls.py, publish.py, and preview.py.
  - Acceptance: migrate default rendering to explicit model version 1, preserve visible output, ordering, routes, safe HTML handling, existing index JSON shape, and index/unpublish rebuilding without source or theme files. Verify public field allowlists, exported data provenance, absence semantics, symlinks, escaping, preview and package parity; document the contract, pass repository checks, and complete independent review. Semantic markup follows in `semantic-site-markup`; custom templates, JavaScript, and new JSON routes are excluded.
