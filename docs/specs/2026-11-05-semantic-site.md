# Semantic site output and page models

Status: accepted direction; implementation queued. There are no current
users, so this design establishes a new semantic baseline without a
backwards-compatibility requirement. [Site themes](../THEMES.md)
documents today's code; its HTML and theme-format promises are replaced
when this design ships. Implementation order and checks are in the
[plan](../../plans/2026-11-05-semantic-site.md).

## Goal and scope

Give themes a stable description of the information on each page, with
useful default HTML that works without JavaScript. Preserve original
values alongside readable presentation so future themes can format
dates, sort sizes, and choose layouts without parsing display strings or
private publisher state.

The first implementation defines a versioned page model, designs
semantic HTML around that information, and reworks or replaces the
themes to suit it. Existing tables, classes, CSS variables, visible
formatting, theme names, and theme format 1 need not survive. Choose the
structure that serves the new model instead of adapting it to the old
presentation.

Themes still supply CSS and declared images in this foundation. Custom
templates, executable theme code, new public page-data routes, and a
browser application require later designs. No Worker deployment,
provisioning, or cloud settings change is part of this work.

## New baseline

The renderer currently passes directory and file tuples to Jinja,
formats byte counts before rendering, truncates revisions in templates,
and emits timestamps as bare text. The index and directory layouts use
tables. These implementation choices do not constrain the replacement.
Use a table where the information is tabular, or semantic lists and
articles where they better describe a collection. CSS controls layout.

This design supersedes the old HTML-hook and compatibility promises in
the [theme design](2026-11-04-site-themes.md). Rework the bundled themes
and custom-theme example against the new output; keeping their names or
appearance is optional. Update authoring docs, validation, preview,
packaged assets, and Worker presentation routes together. No old-theme
adapter, duplicate renderer, legacy route, or migration path is
required.

The new system still meets the
[quality contract](../QUALITY.md#what-quality-means-here): repository
Markdown and raw files remain inert, exported Git history stays stable,
and ordinary clone and pull work. These are correctness requirements
independent of the old presentation.

## Page-model contract, version 1

Build explicit typed models between exported content and rendering.
Default templates consume these models instead of storage dictionaries,
positional listing tuples, or source-repository objects. Keep
construction separate from HTML rendering so future consumers can use
the same information without depending on today's layout.

Every page has `output_version = 1` and `kind = index | tree | blob`.
This version covers the new page-model and semantic-HTML contract.
Version 1 describes the following named records; an implementation may
use frozen dataclasses and tuples. This is a documented rendering
contract, not a new supported Python plugin API or a public JSON
serialization.

| Record | Fields and meaning |
| -- | -- |
| Project | `name`, `description`, full exported `revision`, `updated_at`, generated public `url`, `clone_url`, and archive records. |
| Archive | `format` and generated public `url`. |
| Breadcrumb | `label` and generated public `url`. |
| Entry | `name`, project-relative `path`, `kind` (`directory`, `file`, or `symlink`), generated public `url`, and `size_bytes` (`int` for blob entries, `None` for directories). |
| Index page | Version, kind, and projects sorted by name. |
| Tree page | Version, kind, project, project-relative `path` (empty string at root), breadcrumbs, ordered entries, and an optional rendered README slot. |
| Blob page | Version, kind, project, entry, breadcrumbs, generated public `raw_url`, optional `symlink_target`, and a content state (`source`, `symlink`, or `unavailable`) with an optional highlighted-source slot. |

Define deterministic ordering for projects and entries; the old order is
not a compatibility promise. Record symlinks with their actual kind.
Keep readable size and revision formatting as presentation helpers or
derived properties; they never replace the original values. An
unavailable source view provides a raw download link and a readable
explanation.

Rendered README and highlighted-source slots are explicitly
distinguished from plain text. Only renderer-owned sanitized Markdown,
highlighted source, and autoescaped `pre` wrappers for plaintext READMEs
produce trusted HTML. Descriptions, names, paths, timestamps, and
symlink targets remain escaped. HTML slots are presentation output and
would need a separate decision in any future JSON representation. No
arbitrary model string becomes trusted HTML.

### Provenance and public boundaries

- `revision` is the complete exported commit ID, never the private
  source monorepo commit ID. Treat it as an opaque string rather than
  assuming a fixed hash length.
- `updated_at` is the exported tip's committer timestamp, currently read
  with `git show -s --format=%cI`. Preserve its explicit timezone. It
  does not claim publication time, freshness, or per-file modification
  time.
- `size_bytes` counts exported blob bytes. For symlinks that means the
  stored link-target bytes; never follow a link into the publisher's
  filesystem. Directory sizes are absent. Preserve current omission of
  submodules, which have no exported file content in the renderer.
- Paths are relative to the exported project. URLs come from Partlet's
  central URL builders; never join unescaped path text into HTML links.
- Use an explicit field allowlist. Exclude source paths and identities,
  credentials, approvals, local filesystem locations, storage keys,
  locks, and build-management metadata. Do not serialize `current`
  records, configuration objects, or `FileEntry` wholesale.
- Index construction and unpublish must work from durable public project
  and presentation records without a local source checkout or installed
  theme directory. Their record schemas may be redesigned together;
  decoding legacy records is not required.

### Versioning

Output versions and theme format versions are independent. Start the
HTML/model contract at output version 1 and identify the rewritten theme
contract as format 2. Support that new baseline; reject format-1 packs
clearly before publication instead of introducing adapters. Update all
shipped packs, metadata, examples, and author documentation together.

After this baseline, adding an optional field with defined absence
semantics is compatible. Removing or renaming a documented field or
hook, changing its type or meaning, or changing requiredness requires a
new output version. Breaking theme-contract changes require a new theme
format. Document the supported combination and validate it explicitly.
Versioning establishes future evolution; it does not require keeping
multiple output versions or renderers active now.

The old `/_partlet/index.json` route and project-list shape are not
compatibility obligations. Retain, revise, or remove them according to
the new implementation's actual needs, updating producers, consumers,
routes, tests, and docs together. Do not expose the internal page model
as a new JSON API without a consumer and a serialization and snapshot
consistency design.

## Semantic HTML contract

Keep navigation, clone instructions, downloads, READMEs, source views,
and line anchors functional without scripts or theme CSS. Choose
readable default text and formatting appropriate to the new design. The
old DOM and visual appearance do not constrain it.

Add the following documented hooks and machine-readable values:

| Location | Contract |
| -- | -- |
| Root `html` | `data-partlet-page` (`index`, `tree`, or `blob`) and `data-partlet-output-version="1"`; document the new theme-selection and color-mode hooks. |
| Project record region | `data-partlet-project` containing its public project name, attached to the element grouping that project's information. |
| Project timestamp | `<time datetime="…">…</time>`; the attribute holds `updated_at` and the text is a readable date. |
| Revision code | A `code` element with `data-partlet-revision` holding the complete exported revision; its visible text may be abbreviated. |
| Entry region | `data-partlet-entry-kind` and `data-partlet-path` on the element grouping that entry's information. |
| File size | `<data value="1536">1.5 KiB</data>`; `value` is the decimal byte count, independent of the visible size format. |

For example, a project timestamp remains ordinary useful content:

```html
<time datetime="2026-11-05T09:00:00+00:00">5 November 2026</time>
```

Use meaningful headings, a main landmark, and labeled breadcrumb
navigation. If a listing uses a table, provide an accessible name and
column headers with appropriate scope. If it uses lists or articles,
express that hierarchy directly. Group names, descriptions, revisions,
timestamps, file metadata, README content, and source lines so themes
can target their meaning without depending on positional selectors.
Document the new hooks and CSS tokens. Support narrow screens, keyboard
focus, code scrolling, and addressable source lines.

Only documented fields, attributes, tokens, and hooks in this new
baseline become future compatibility promises. Incidental whitespace and
wrappers are not. The semantic structure and data must remain useful
without theme CSS; themes may arrange those regions differently.

Validate timestamps when constructing the new model and report invalid
inputs clearly. There is no legacy timestamp decoder or fallback path.

## Rendering and publication

Build the model from one exported snapshot and use it for that page's
values and URLs. Reuse it for local builds, publication, and disposable
preview. Do not introduce browser fetches or a second rendering path in
the Worker.

Include an explicit renderer contract revision in project build identity
when semantic output ships. Increment it for output changes that require
regeneration. Unchanged Git history and theme inputs must still
regenerate pages after this renderer upgrade; export hashes and history
approval remain unaffected. Output contract version alone is
insufficient as a renderer cache key, because compatible markup changes
also need builds.

Keep publication internally consistent: fingerprint theme resources and
upload them before pages or live pointers reference them. Assets needed
by currently live pages must remain available, including projects left
unchanged after partial publication failures. That reference integrity
is required within the new baseline; retaining obsolete release output
solely for backwards compatibility is unnecessary.

Index rebuilding uses the same model constructor when publishing and
unpublishing, recovering presentation from durable records. Public
presentation routes and record schemas may change together; keep raw
files isolated and Git serving functional. Remove obsolete presentation
paths rather than maintaining a parallel legacy system. No new storage
garbage collector is required by this work.

## Future extensions

A later template capability could consume this model during publishing
to produce substantially different layouts, including cards or a split
repository browser. It needs an explicit trust and sandbox design,
escaping rules, committed-input validation, build identity, package
support, and compatibility handling before implementation.

Optional publisher-trusted theme JavaScript could add filtering,
sorting, relative dates, and interactive navigation. It needs a separate
asset and CSP design that preserves the isolation of repository Markdown
and raw files. Merely allowing all same-origin scripts would not
establish that boundary. Baseline navigation and content must remain
usable if a script fails or is unavailable.

Expose page JSON only with an actual consumer and a design for safe
serialization, minimal public fields, and consistency with the page's
publication snapshot. These extensions are not authorized by
implementing this foundation.

## Acceptance evidence

- Model-level checks verify raw values, provenance, absence semantics,
  deterministic ordering, symlinks, and the public field allowlist.
- A parsed-HTML check verifies meaningful values and the new hooks
  across index, root and nested directories, source, symlink, binary,
  and oversized-file pages. Include Markdown and plaintext READMEs,
  unusual names, escaping, and rejection of invalid model timestamps.
  Verify the new contract rather than equality with old HTML or JSON.
- Exercise index rebuilding and unpublish from the new durable records
  without the source checkout or theme files. Check every retained or
  changed presentation route against the new contract.
- Verify renderer-only upgrades regenerate pages without changing
  exported commits or requiring renewed history approval. Cover local
  build, preview, and publication using synthetic repositories.
- Verify unsupported old theme packs fail clearly and every shipped
  theme plus the rewritten custom example uses the new contract. Inspect
  light and dark modes, desktop and narrow widths, keyboard focus,
  README links, and source line anchors. Save representative browser
  evidence. No screenshot parity with the old themes is required.
- Exercise partial publication to show live pages retain their
  referenced assets and do not mix incompatible output and theme
  formats.
- Run the repository's required checks. Local and simulated-store proof
  establishes neither a hosted deployment nor behavior on private data.
