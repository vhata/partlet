# Semantic site implementation plan

Status: queued; no product behavior has changed. The
[semantic site design](../docs/specs/2026-11-05-semantic-site.md) is the
authoritative contract. Both steps need independent review and the
normal repository gates before they are ready for the user's final
review.

## 1. Versioned page models

Queue: `site-page-models`.

Introduce typed, named project, entry, breadcrumb, archive, and page
records under `src/partlet/site/`. Keep the model separate from storage
and Jinja, with explicit construction from validated values in the
exported snapshot. Preserve the existing publication approval boundary;
disposable preview still works for unapproved projects. Inspect
`site/render.py`, `site/tree.py`, `site/urls.py`, `publish.py`, and
`preview.py` together before changing interfaces.

Migrate the existing templates to consume the models while preserving
visible output, URLs, ordering, and CSS hooks. Retain raw byte counts
and full exported revisions; derive readable strings only for
presentation. Distinguish plain text from renderer-produced safe HTML.
Preserve the public index JSON shape and the durable-record path used by
unpublish.

Checks must exercise realistic exported entries and index records,
including directory absence values, symlink targets, unusual names, and
escaping. Compare generated pages and the index JSON interface with the
current behavior. Verify preview and installed-package rendering use the
same constructors. Document the model's version and extension rules in
the theme-author guide without advertising unsupported plugins or JSON.

Deliver this as a separately reviewable refactor. Its models become the
shared interface for the semantic markup step; do not run concurrent
writers over renderer, templates, or the theme-author guide.

## 2. Semantic markup and renderer rebuild identity

Queue: `semantic-site-markup`; depends on `site-page-models`.

Use the model to add the exact semantic elements and attributes in the
design. Preserve table styling hooks, code line anchors, visible values,
raw/download links, and functioning pages without JavaScript. Add table
headers or accessible names and breadcrumb labels with corresponding
default styling. Keep format-1 theme compatibility and Worker CSP
intact.

Introduce a renderer contract revision into project build identity. Test
that changing that revision rebuilds pages for unchanged exported
history and theme inputs without modifying exported commit IDs or
approval requirements. Keep this revision separate from model and theme
versions.

Use parsed HTML to verify the contract on every page kind and content
state. Check malformed legacy timestamps and unpublish with only durable
public records and stored presentation. Exercise local build, preview,
and simulated publication. Inspect Classic, Paper, Terminal, and Copper
at desktop and narrow widths in both color modes. Record browser checks
and representative screenshots; automated attribute checks alone do not
establish appearance or accessibility.

Update `docs/THEMES.md` with supported semantics, raw values, stable
hooks, and compatibility rules, and link the model documentation there.
Run `bash scripts/check.sh` and queue/link checks. Complete an
independent review of the actual combined changes before marking the PR
ready.

## Deferred decisions

Custom build-time templates, theme JavaScript, and page-data JSON need
their own concrete consumers and designs. They are outside these queue
entries. Preserve the default static site and current trust boundary
through both implementation steps. Provisioning and deployment remain
the user's.
