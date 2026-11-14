# Page models

The site uses frozen, named rendering records in
`src/partlet/site/models.py`. Constructors in `site/build.py` project
exported snapshots or durable public records into these models;
`site/render.py` passes a single `page` to each default template.
Construction does not load Jinja templates or access a source checkout.
This is a rendering contract, not a supported Python plugin API or a
public JSON endpoint.

Every page has `output_version = 1` and `kind` (`index`, `tree`, or
`blob`). The complete field definitions are in the
[version-1 design](specs/2026-11-05-semantic-site.md#page-model-contract-version-1).
The semantic HTML hooks and theme format 2 are a subsequent step; this
refactor retains the current layout and theme format.

## Values and provenance

- Projects carry `name`, `description`, full exported `revision`,
  `updated_at`, generated `url` and `clone_url`, and named `archives`
  (`format`, `url`). Revisions are opaque, with no fixed hash length.
- `updated_at` is the exported tip's committer time from Git `%cI`,
  preserved exactly, including its timezone (`Z` or a numeric offset).
  Construction requires seconds, a valid calendar date and time, and an
  explicit timezone. Missing or invalid timestamps fail clearly; there
  is no fallback decoder. This is neither publication time nor per-file
  modification time.
- Entries carry `name`, project-relative `path`, `kind`, generated
  `url`, and `size_bytes`. Directory sizes are `None`; file and symlink
  sizes count exported blob bytes, including zero. Symlinks are never
  followed. Gitlinks remain omitted. All links use the central URL
  builders. Clone URLs require HTTP(S) without credentials, query or
  fragment.
- Tree pages carry their project, relative `path` (empty at root), named
  breadcrumbs (`label`, `url`), entries and optional `readme_html`.
- Blob pages carry their project, entry, breadcrumbs, `raw_url`,
  optional `symlink_target`, `content_state` and optional `source_html`.
  States are `source`, `symlink` and `unavailable`. Binary and oversized
  blobs use the latter state and retain their raw download. Non-UTF-8
  symlink targets use replacement characters for display only; raw bytes
  and byte counts remain intact.

Projects sort by name using Python string order. Listings put
directories first, then files and symlinks together, each group sorted
by name. Snapshot pages sort directory paths first and blob paths
second. README selection uses the documented candidate order in the
constructor; when names differ only in case, the last name in string
order wins.

## Trust and durable data

The durable-record adapter explicitly selects only `name`,
`description`, `tip` and `updated`. It constructs public links using the
site's public base URL. No source path, approval, credentials, storage
key, lock or build metadata enters the model. Index rebuilding and
unpublish use these durable fields and stored theme presentation without
reading a source repository or installed custom theme directory. Corrupt
project records are omitted by the index publisher, as before.

Only sanitized renderer Markdown, escaped plaintext README wrappers and
syntax-highlighted source produce `Markup` HTML slots. Ordinary strings
remain autoescaped, even if supplied in an HTML slot. Templates do not
apply `safe` to arbitrary strings. Display size and abbreviated revision
formatting never replace the underlying values.

Optional fields with defined absence semantics may be added to version

1. Removing or renaming fields, changing their type or meaning, or
   changing requiredness requires a new output version. Theme versions
   and renderer build identity are separate contracts.
