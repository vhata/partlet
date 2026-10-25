# Partlet design

Date: 2026-10-15
Status: draft for review

## Purpose

Partlet publishes selected directories of a private Git monorepo as public,
read-only "virtual repositories". Each published directory gets a website
(README, directory browser, file viewer, raw files, downloads) and a clone URL
that works with ordinary `git clone` and `git pull`, carrying that directory's
own history.

The everyday workflow: edit everything together in the monorepo, commit, push
once, and the selected projects publish automatically.

### Audience

v1 serves one user and one monorepo. Nothing in the design should prevent
other people from adopting it later, so the tool lives in its own repository
and the monorepo only carries a manifest, a small workflow file, and secrets.
Pointing a different monorepo at a Partlet site means copying those two files
and adding the secrets.

### Non-goals for v1

- Pushes, pull requests, or any write path from the public side.
- A web history browser (log, blame, diffs). Pages show the tip of the
  publishing branch only.
- Multiple source monorepos on one site (the storage layout leaves room for
  it; see "R2 layout").
- Automatic deletion of projects removed from the manifest.
- Redirects for renamed public project names.

## Overview

```
private monorepo ──push──> GitHub Actions ──> partlet publish ──> R2 bucket <── Cloudflare Worker <── visitors / git
  partlet.toml               (composite action        (export, check,          (read-only routing,
  .github/workflows/          from this repo)          scan, pack, render,      no GitHub access)
    partlet.yml                                        upload)
```

The publisher has access to the monorepo (via the Actions checkout) and holds
an R2 write token. The Worker has neither: it only reads already-public
exports from R2.

## Repositories and components

### This repository (Partlet)

```
partlet/
  pyproject.toml
  src/partlet/
    manifest.py      load and validate partlet.toml
    export.py        filter-repo extraction into a bare repository
    history.py       approval pin and fast-forward checks
    scan.py          gitleaks wrapper
    gitstatic.py     prepare dumb-HTTP files (refs, packs, info files)
    archive.py       deterministic .tar.gz / .zip via git archive
    site/            renderer: Jinja2 templates, markdown-it-py, Pygments
    store.py         Store interface; R2 (boto3, S3 API) and local-directory backends
    cli.py           partlet review | build | publish | unpublish
  worker/            Cloudflare Worker (TypeScript), wrangler.toml
  action.yml         composite GitHub Action used by the monorepo
  tests/
  .github/workflows/ CI for this repository
```

Python 3.12, packaged with `pyproject.toml`, developed in a project-specific
virtualenv. The Worker is TypeScript, built and deployed with wrangler.

### The monorepo

1. `partlet.toml` at the repository root:

   ```toml
   [site]
   source = "jonathan"            # R2 key prefix for this source
   branch = "main"                # publishing branch
   base_url = "https://partlet.example"
   mailmap = ".partlet-mailmap"   # optional; see "Author metadata"

   [projects.foo]
   path = "tools/foo"
   previous_paths = ["scripts/foo"]
   description = "Short blurb for the index"
   approved = "3f9c2e1..."        # export commit approved by `partlet review`
   # allow_rewrite_of = "..."     # written by `partlet review --allow-rewrite`
   ```

2. `.github/workflows/partlet.yml`: triggers on push to the publishing branch
   and on `workflow_dispatch`; checks out with `fetch-depth: 0`; declares
   `concurrency: { group: partlet, cancel-in-progress: false }`; runs
   `uses: <owner>/partlet@v1` with R2 credentials from secrets.

3. Secrets: R2 account ID, access key ID, secret access key, bucket name. The
   token is scoped to write the one bucket.

The composite action installs Python, installs Partlet from the action's own
checkout (so the version is pinned by the action ref), installs
`git-filter-repo` and a pinned gitleaks release, and runs `partlet publish`.

## Manifest rules

- Project names match `[a-z0-9][a-z0-9._-]*` and are unique. Names ending in
  `.git` are rejected (the Worker uses that suffix as an alias).
- `path` must exist as a directory at the tip of the publishing branch. If it
  does not, the project fails with a message suggesting the directory was moved
  and that `path` and `previous_paths` need updating. This prevents publishing
  a commit that deletes the whole project.
- `previous_paths` lists earlier locations of the directory. All of `path` and
  `previous_paths` are mapped to the export root.
- A project without `approved` is skipped and logged; this is not an error.
- The manifest is edited programmatically with tomlkit so comments and
  formatting survive.

## Export

For each project:

1. Clone the monorepo's publishing branch into a fresh temporary bare
   repository (single branch, full history).
2. Run `git filter-repo` with `--path` for `path` and each of
   `previous_paths`, and `--path-rename <p>/:` for each, so their contents land
   at the root. Apply `--mailmap` if the site configures one. Keep only
   `refs/heads/main`; drop tags and other refs.
3. The resulting tip commit is the export tip.

### Stable commit identities

Given the same monorepo history, path list, mailmap, and tool versions, the
export produces identical commit hashes. The git and filter-repo versions are
pinned in the action. A test runs the same export twice and compares hashes.

New commits in the monorepo append to the export without changing earlier
export commits, as long as the path list and mailmap are unchanged.

### Directory moves

When a published directory moves (for example `scripts/foo` to `tools/foo`),
the same push updates the manifest to `path = "tools/foo"` and
`previous_paths = ["scripts/foo"]`. The re-export is a fast-forward of what was
published:

- Commits before the move only touched `scripts/foo`. With that renamed to the
  root, their trees, metadata and parents are unchanged, so their hashes are
  unchanged.
- The move commit produces the same root tree as its parent and is pruned as
  empty.
- Later commits touch `tools/foo`, renamed to the root, and append.

Adding a path to `previous_paths` rewrites history only if that path appears
in commits that were already published, or if the new location held other
content before the move. The fast-forward check below catches both. `partlet
review` warns about undeclared earlier locations before first publication so
this can be settled up front.

## History checks

The previously published tip is read back from R2 (the project's published
`info/refs`). There is no other state store.

- If a published tip exists, it must be an ancestor of the new export tip
  (`git merge-base --is-ancestor`). Otherwise the project fails as a rewrite.
- If nothing is published yet, the `approved` commit must be an ancestor of, or
  equal to, the new export tip.
- Exception: if `allow_rewrite_of` equals the current published tip, a
  non-fast-forward is permitted, provided `approved` is an ancestor of or equal
  to the new tip. After that publish the published tip changes, so the field no
  longer matches and has no further effect.
- If the new tip equals the published tip, Git files are not re-uploaded; the
  site is re-rendered only if the build ID changed (see "Site").

## Secret scanning

- In CI, gitleaks scans only the commits being added: `published..new`, or
  `approved..new` on first publication. A finding fails that project.
- The full history up to `approved` is scanned locally during `partlet review`.
- gitleaks configuration: if the monorepo has a `.gitleaks.toml` at its root,
  it is used; otherwise gitleaks defaults apply.

## Dumb-HTTP Git layout

Each published project is a bare-repository file layout in R2, generated by
the publisher rather than by a server-side Git process.

- `HEAD`: `ref: refs/heads/main`.
- `info/refs`: one line, `<tip sha>\trefs/heads/main`.
- `objects/pack/pack-*.pack` and `.idx`: each publish adds one new pack
  containing objects reachable from the new tip and not from the previously
  published tip (`git pack-objects --revs`). Packs are never modified after
  upload, so a `git pull` downloads only new packs.
- `objects/info/packs`: lists the current packs.
- Consolidation: when a project has more than 20 packs, the publisher writes
  one pack containing everything, updates `objects/info/packs` to list only
  that pack once `info/refs` has moved, and deletes the superseded packs on
  the following publish, so clients in the middle of a fetch are not broken.
- After a permitted rewrite, the publisher writes a single full pack and
  treats all earlier packs as superseded.

## Site

Pre-rendered by the publisher from the export tip's tree. The Worker does no
rendering.

- Project page: rendered README (Markdown via markdown-it-py; other formats
  shown as plain text) and the root directory listing.
- Directory listings for every directory.
- File viewer pages with Pygments syntax highlighting.
- Files that are binary or larger than a size cap (default 1 MiB) get a page
  with a raw download link and no viewer.
- Raw copies of every file.
- Site index page listing all published projects with description, tip, and
  last-updated time, plus `index.json` with the same data.
- Pages use plain HTML and CSS, no JavaScript.

Each render goes into a new build prefix. The build ID is a hash of the export
tip SHA and the Partlet version, so changing templates (a new Partlet release)
produces a new build. A `workflow_dispatch` run re-renders every project from
existing exports without touching Git history.

## Archives

`git archive` of the export tip as `.tar.gz` and `.zip`, prefixed with the
project name, stored by tip SHA. The Worker serves the latest archive at a
stable URL.

## Upload order

1. New packs, the new site build, and archives (all new keys, nothing
   references them yet).
2. Pointers: `objects/info/packs`, `info/refs`, `HEAD`, then the project's
   `current` file naming the live site build and tip. A publish that drops
   packs (consolidation, rewrite) first lists the old and new packs
   together, and writes the shorter list only after `info/refs` has moved.
3. Cleanup, per project: delete every pack, site build and archive that
   neither the pointers nor the previous publish name. `current` records the
   previous publish's build, tip and packs, so superseded keys get one
   publish of grace. A run that finds the project unchanged cleans up too.
4. Site index (`index.html`, `index.json`), once every project is done.

R2 has no multi-object transaction. This order means refs never name an
object that is missing or in a pack the pack list leaves out. An interrupted
publish leaves at worst unreferenced keys, which the next run deletes, or a
pack list naming a pack the refs no longer need, which stays listed until the
next consolidation or rewrite drops it.

## R2 layout

```
<source>/index.html
<source>/index.json
<source>/p/<name>/current                    JSON: live build id, tip sha, updated time,
                                             previous build, tip and packs
<source>/p/<name>/git/HEAD
<source>/p/<name>/git/info/refs
<source>/p/<name>/git/objects/info/packs
<source>/p/<name>/git/objects/pack/pack-*.{pack,idx}
<source>/p/<name>/site/<build>/...           rendered pages and raw files
<source>/p/<name>/archive/<sha>.{tar.gz,zip}
```

Everything sits under a per-source prefix so a future version can serve
several sources from one bucket.

## Worker

### URLs

For a project named `foo`:

```
/                          site index
/foo                       project page
/foo/tree/<path>           directory listing
/foo/blob/<path>           file viewer
/foo/raw/<path>            raw file
/foo/archive/foo.tar.gz    latest archive (also .zip)
/foo/HEAD
/foo/info/refs
/foo/objects/...           Git dumb-HTTP files
/foo.git/...               alias for /foo/...
```

Project files are always under `tree/`, `blob/` or `raw/`, so the top-level
names `HEAD`, `info`, and `objects` are reserved for Git and cannot collide
with project contents.

### Behaviour

- Configuration: an R2 bucket binding and a `SOURCE` variable. No GitHub
  credentials. The code has no write paths.
- Page, raw, and archive requests read `p/<name>/current` to resolve the live
  build and tip.
- `info/refs?service=git-upload-pack` returns the plain `info/refs` file as
  `text/plain`. Git clients then fall back to the dumb protocol on their own.
- Unknown projects or paths return a 404 page.

### Caching

- Packs, archive files by SHA, and anything under a build prefix: `public,
  max-age=31536000, immutable`.
- `HEAD`, `info/refs`, `objects/info/packs`, and pages served at stable URLs:
  `max-age=60` with an ETag from R2.

### Response safety

- `raw/` serves text as `text/plain; charset=utf-8`; png, jpg, gif and webp
  with their real types; everything else, including SVG and HTML, as
  `application/octet-stream` with `Content-Disposition: attachment`.
- All responses send `X-Content-Type-Options: nosniff`.
- Rendered pages send a CSP that allows no scripts.

### Deployment

`wrangler deploy` from `worker/`, with the bucket name, `SOURCE`, and custom
domain in `wrangler.toml`. The README documents setting up the R2 bucket, the
scoped token, the Worker, and the monorepo secrets. These steps are run by the
user; R2 and Workers are billable services.

## `partlet review`

Run locally from a monorepo checkout: `partlet review <name>`.

1. Builds the export with the same code CI uses, in a temporary directory.
2. Reports:
   - every path that ever existed in the export, with deleted paths marked;
   - files over the size cap;
   - distinct author and committer names and emails;
   - commit count, and commit messages in a pager;
   - gitleaks findings over the full export history;
   - undeclared earlier locations: files in `path` whose history begins with a
     rename from outside `path` and `previous_paths`, with a suggestion to add
     that location to `previous_paths`.
3. Asks `Approve tip <sha> for publication? [y/N]`. On yes, writes `approved`
   into `partlet.toml`.

`--allow-rewrite` additionally writes `allow_rewrite_of = "<current published
tip>"`.

### Author metadata

The optional site-level `mailmap` is applied by filter-repo during export. It
changes commit hashes, so it must be settled before a project is first
published (or treated as an explicit rewrite afterwards). The review report
lists emails so this can be decided before approval.

## Other commands

- `partlet build --out <dir>`: run the full pipeline into a local directory
  store, for previewing without Cloudflare.
- `partlet publish`: the CI entry point; runs every approved project against
  the R2 store.
- `partlet unpublish <name>`: deletes a project's keys from R2 and rebuilds
  the index. Never run automatically. If the project is still in the manifest
  with an `approved` pin, the next publish restores it, so remove the entry
  first.

The site index is built from the projects that have a `current` file in R2,
not from the manifest. A project dropped from the manifest therefore stays
listed and served until it is unpublished.

## Error handling

- Each project succeeds or fails independently. Failures do not stop other
  projects; the index reflects what succeeded. The job exits non-zero if any
  project failed.
- A summary table (project, status, tip, reason) is written to
  `$GITHUB_STEP_SUMMARY`.
- Retrying after an interrupted upload is safe: packs are content-addressed,
  builds are keyed by build ID, and pointers move last.
- The workflow's `concurrency` group serialises publishes, because the history
  check reads published state and then writes it, and because cleanup deletes
  every key no pointer names, which includes another publish's uploads that
  are not named yet.

## Testing

- Python unit tests: manifest validation, history-check decisions, build ID,
  content-type policy shared with the Worker.
- Python integration tests (pytest) on synthetic monorepos built with real git
  commands, covering moves, deletions, merges, neighbouring directories, and a
  planted fake secret. They assert:
  - only declared paths appear in the export;
  - repeated exports give identical hashes;
  - a move made after publication fast-forwards;
  - adding `previous_paths` retroactively is detected as a rewrite;
  - a missing `path` fails the project;
  - the planted secret blocks the project;
  - `allow_rewrite_of` permits exactly one rewrite.
- Worker tests (vitest with the Workers pool): routing, reserved names, raw
  content types, cache headers, the dumb-HTTP `info/refs` response, `.git`
  alias, 404s.
- End-to-end: publish into a local store, serve with `wrangler dev` and local
  R2, `git clone`, publish more commits, `git pull`, and check the clone
  matches the export.
- CI for this repository runs all of the above.
