# Semantic site implementation plan

Status: step 1 implemented; step 2 remains queued. The
[semantic site design](../docs/specs/2026-11-05-semantic-site.md) is the
authoritative contract. Both steps need independent review and the
normal repository gates before they are ready for the user's final
review.

There are no current users. Establish a new semantic baseline and
redesign themes around it; old HTML, CSS hooks, theme packs, visible
formatting, and presentation JSON have no compatibility requirement.
Keep explicit output and theme versions for future evolution. No
migration adapters or parallel legacy renderer are needed.

## 1. Versioned page models

Queue: `site-page-models`.

Introduce typed, named project, entry, breadcrumb, archive, and page
records under `src/partlet/site/`. Keep the model separate from storage
and Jinja, with explicit construction from validated values in the
exported snapshot. Preserve the existing publication approval boundary;
disposable preview still works for unapproved projects. Inspect
`site/render.py`, `site/tree.py`, `site/urls.py`, `publish.py`, and
`preview.py` together before changing interfaces.

Move default rendering onto output-version-1 models. Retain raw byte
counts and full exported revisions; derive readable strings only for
presentation. Define deterministic ordering and distinguish plain text
from renderer-produced safe HTML. Keep source-free index rebuilding and
unpublish working; durable schemas may change coherently. Old HTML and
index JSON are not acceptance snapshots or constraints on the model.

Checks must exercise realistic exported entries and index records,
including directory absence values, symlink targets, unusual names, and
escaping. Assert the new data contract, its timestamp validation, and
its public-data boundary. Verify preview and installed-package rendering
use the same constructors. Document the model's version and extension
rules without advertising unsupported plugins or JSON.

Deliver this as a separately reviewable refactor. Its models become the
shared interface for the semantic markup step; do not run concurrent
writers over renderer, templates, or the theme-author guide. This step
prepares the model; publish the new HTML/theme contract together in step
2, including its supported-version documentation.

## 2. Semantic markup, redesigned themes, and rebuild identity

Queue: `semantic-site-markup`; depends on `site-page-models`.

Design the HTML around the model's information and the semantic elements
and attributes in the spec. Choose tables, lists, or articles according
to their meaning. Replace old classes, wrappers, and CSS tokens where
useful. Keep navigation, raw/download links, and addressable source
lines functional without JavaScript. Provide accessible headings,
landmarks, listing structure, and breadcrumb labels.

Rework or replace bundled themes and the custom-theme example against
that structure. Set their theme format to 2, reject old packs clearly,
and update validation, selection, defaults, preview, packaged assets,
author docs, and Worker presentation routes as one coherent change.
Retaining existing theme names or appearance is optional. Retire unused
legacy presentation paths; do not add adapters or a second renderer.
Keep repository content inert and raw files isolated.

Introduce a renderer contract revision into project build identity. Test
that changing that revision rebuilds pages for unchanged exported
history and theme inputs without modifying exported commit IDs or
approval requirements. Keep this revision separate from model and theme
versions.

Use parsed HTML to verify the contract on every page kind and content
state. Verify timestamp validation and unpublish using only the new
durable public records and stored presentation. Exercise local build,
preview, and simulated publication, including partial failures: assets
referenced by live pages must survive. Inspect every shipped theme and
the rewritten custom example at desktop and narrow widths in both color
modes. Record browser checks and representative screenshots; automated
attribute checks alone do not establish appearance or accessibility.

Update `docs/THEMES.md` with supported semantics, raw values, stable
hooks, and compatibility rules, and link the model documentation there.
Run `bash scripts/check.sh` and queue/link checks. Complete an
independent review of the actual combined changes before marking the PR
ready.

## Deferred decisions

Custom build-time templates, theme JavaScript, and page-data JSON need
their own concrete consumers and designs. They are outside these queue
entries. Deliver a useful static site and maintain the
repository-content trust boundary through both implementation steps.
Provisioning and deployment remain the user's.
