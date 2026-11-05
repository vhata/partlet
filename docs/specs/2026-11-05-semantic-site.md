# Semantic site output and page models

Status: accepted direction; implementation queued. The current supported
theme contract remains [Site themes](../THEMES.md). Implementation order
and checks are in the [plan](../../plans/2026-11-05-semantic-site.md).

## Goal and scope

Give themes a stable description of the information on each page, with
useful default HTML that works without JavaScript. Preserve original
values alongside readable presentation so future themes can format
dates, sort sizes, and choose layouts without parsing display strings or
private publisher state.

The first implementation defines a versioned page model and adds
semantic markup to Partlet's existing templates. Theme format 1 remains
CSS and declared images only. Custom templates, executable theme code,
new public JSON routes, and a browser application require later designs.
No Worker deployment, provisioning, or cloud settings change is part of
this work.

## Current constraints

The renderer currently passes directory and file tuples to Jinja,
formats byte counts before rendering, truncates revisions in templates,
and emits timestamps as bare text. The index and directory layouts use
tables. A table is appropriate for tabular information; this design
improves its meaning and access to values while preserving its existing
styling hooks.

The [theme design](2026-11-04-site-themes.md) promises stable CSS tokens
and hooks including `table.listing`. Those promises still apply. The
Worker blocks scripts, and repository Markdown and raw files remain
inert under the
[quality contract](../QUALITY.md#what-quality-means-here).

## Page-model contract, version 1

Build explicit typed models between exported content and rendering.
Default templates consume these models instead of storage dictionaries,
positional listing tuples, or source-repository objects. Keep
construction separate from HTML rendering so future consumers can use
the same information without depending on today's layout.

Every page has `model_version = 1` and `kind = index | tree | blob`.
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

Retain directory-first ordering and lexical name ordering within each
group. Symlinks stay among file entries, with their kind recorded. Keep
readable size and revision formatting as presentation helpers or derived
properties; they never replace the original values. An unavailable
source view retains the existing download link and explanation.

Rendered README and highlighted-source slots are explicitly
distinguished from plain text. Their HTML producers remain the existing
Markdown sanitizer, source highlighter, and autoescaped `pre` wrapper
for plaintext READMEs. Descriptions, names, paths, timestamps, and
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
  existing URL builders; never join unescaped path text into HTML links.
- Use an explicit field allowlist. Exclude source paths and identities,
  credentials, approvals, local filesystem locations, storage keys,
  locks, and build-management metadata. Do not serialize `current`
  records, configuration objects, or `FileEntry` wholesale.
- Index construction must still work from the existing public fields in
  durable project records. Unpublish must rebuild it without a local
  source checkout or installed theme directory.

### Versioning

Model versions and theme format versions are independent. Adding an
optional field with defined absence semantics is compatible. Removing or
renaming a field, changing its type or meaning, or changing requiredness
requires a new model version. Document additions and their fallback
behavior. Keep versioning explicit before offering external consumers.

Do not change the existing public `/_partlet/index.json` project-list
shape or reinterpret it as this page model. It is an existing interface.
Any later page-data endpoint needs its own serialization, compatibility,
and publication-consistency design.

## Semantic HTML contract

Keep navigation, clone instructions, downloads, READMEs, source views,
and line anchors functional without scripts or theme CSS. Maintain
readable default text, including the existing timestamp and size display
unless a separate presentation change is justified.

Add the following documented hooks and machine-readable values:

| Location | Contract |
| -- | -- |
| Root `html` | `data-partlet-page` (`index`, `tree`, or `blob`) and `data-partlet-model-version="1"`, alongside existing theme and mode attributes. |
| Project record region | `data-partlet-project` containing its public project name; one index row or the project page's `main` region. |
| Project timestamp | `<time datetime="…">…</time>` inside the existing updated cell or tip paragraph. The attribute holds `updated_at`. |
| Revision code | Existing abbreviated visible revision, with `data-partlet-revision` holding the complete exported revision. |
| Listing row | `data-partlet-entry-kind` and `data-partlet-path` identifying the exported entry. |
| File size | `<data value="1536">1.5 KiB</data>` inside the existing size cell or file-info region; `value` is the decimal byte count. |

For example, a project timestamp remains ordinary useful content:

```html
<td class="updated">
  <time datetime="2026-11-05T09:00:00+00:00">
    2026-11-05T09:00:00+00:00
  </time>
</td>
```

Use table captions or accessible names, column headers with appropriate
scope, and a labeled breadcrumb navigation region. Preserve existing
classes and elements that format-1 themes rely on, including
`header.top`, `main`, `.crumbs`, `table.listing`, `article.readme`,
`.hl`, and `.hl .linenos`. Support narrow screens and keyboard
navigation. Changes to header markup need corresponding default styling
so existing themes remain usable.

Only documented fields, attributes, tokens, and hooks are compatibility
promises. Incidental whitespace and wrappers are not. Additive markup
must still be checked against bundled themes and the Copper example;
preserving class names alone does not establish visual compatibility.

For malformed legacy timestamp values, emit escaped readable text and
omit the `time` element rather than inventing a date or invalid
`datetime`. Valid current publication timestamps retain their value.

## Rendering and publication

Build the model from one exported snapshot and use it for that page's
values and URLs. Reuse it for local builds, publication, and disposable
preview. Do not introduce browser fetches or a second rendering path in
the Worker.

Include an explicit renderer contract revision in project build identity
when semantic output ships. Increment it for output changes that require
regeneration. Unchanged Git history and theme inputs must still
regenerate pages after this renderer upgrade; export hashes and history
approval remain unaffected. Model compatibility version alone is
insufficient as a renderer cache key, because compatible markup changes
also need builds.

Keep immutable theme resources, current pointers, public routes,
raw-file headers, and the existing index JSON shape compatible. Index
rebuilding uses the same model constructor whether publishing or
unpublishing, including selected theme recovery and legacy records.
Cached older pages remain usable with their existing assets.

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
- A parsed-HTML check verifies meaningful values and stable hooks across
  index, root and nested directories, source, symlink, binary, and
  oversized-file pages. Include Markdown and plaintext READMEs, unusual
  names, escaping, and malformed legacy timestamps. Do not make
  whitespace snapshots the contract.
- Compare the existing index JSON interface before and after the change.
  Exercise index rebuilding and unpublish from stored records without
  the source checkout or theme files.
- Verify renderer-only upgrades regenerate pages without changing
  exported commits or requiring renewed history approval. Cover local
  build, preview, and publication using synthetic repositories.
- Inspect bundled themes and Copper in light and dark modes, at desktop
  and narrow widths, including header changes, keyboard focus, README
  links, and source line anchors. Save representative browser evidence.
- Run the repository's required checks. Local and simulated-store proof
  establishes neither a hosted deployment nor behavior on private data.
