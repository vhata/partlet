# Partlet Worker

The Worker is the public-facing part of Partlet. It receives requests
for your site and serves the files and Git objects the publisher stored
in Cloudflare R2. It does not export repositories or render pages, and
it needs no credentials for the private source repository.

**Setting up your public site?** Follow
[Publish your first site](../docs/GETTING_STARTED.md) for bucket
creation, credentials, domain configuration, and deployment. This page
covers local previews, Worker behavior, and development.

## Preview local publisher output

A local preview uses simulated R2 and needs no Cloudflare account. First
follow the README's
[installation and approval steps](../README.md#get-started). A project
without an `approved` hash is skipped by `build`. Use a harmless test
project while learning this flow.

Install Node from [.node-version](.node-version) and npm >=11.19. Set
these paths to your checkouts, then run:

```bash
PARTLET_DIR=/absolute/path/to/partlet
SOURCE_REPO=/absolute/path/to/my-monorepo
cd "$PARTLET_DIR"
npm ci --prefix worker --no-audit --no-fund
PARTLET_PREVIEW="$(mktemp -d)"
PARTLET_LOCAL_R2="$(mktemp -d)"
"$PARTLET_DIR/.venv/bin/partlet" build --repo "$SOURCE_REPO" \
  --out "$PARTLET_PREVIEW" --scan
```

Expect `published` for the approved project. `build` writes a directory
of internal storage keys, rather than a directly browsable website. Load
it into the local Worker's bucket and start the server:

```bash
cd "$PARTLET_DIR/worker"
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
PARTLET_BUCKET=replace-me
node tools/seed-r2.mjs "$PARTLET_PREVIEW" "$PARTLET_LOCAL_R2" "$PARTLET_BUCKET"
node_modules/.bin/wrangler dev --local --ip 127.0.0.1 \
  --port 8787 --inspector-port 0 --var SOURCE:my-monorepo \
  --persist-to "$PARTLET_LOCAL_R2"
```

`PARTLET_BUCKET` must match `bucket_name` in `worker/wrangler.toml`; the
unedited file uses `replace-me`. Replace `my-monorepo` in the `--var`
argument with the manifest's `site.source`. The same persistence
directory must be used by both commands. The seeder replaces the local
bucket's entire contents, so use the fresh temporary directory above.

Open `http://127.0.0.1:8787/`. In another terminal, clone your project
(replace `foo` if needed):

```bash
git clone http://127.0.0.1:8787/foo partlet-preview-clone
```

The page's displayed clone URL uses the manifest's `base_url`; use the
localhost URL above for local cloning. Stop Wrangler with Ctrl-C. To
preview an update, commit it on your source publishing branch, rerun
`build`, reseed the same local store with the server stopped, then
restart Wrangler. Keep the shell variables if you want to reuse these
commands. See [publisher commands](../docs/PUBLISHING.md#commands) for
build options.

## User-run deployment

Use the [first-site guide](../docs/GETTING_STARTED.md) for the
deployment sequence. R2 and Workers are billable; creation and
deployment are user-run operations. Keep direct bucket access disabled
and verify the site through its public Worker domain after publishing.
Local preview and a dry-run bundle do not establish hosted behavior or
account setup.

## Public contract and safety

Routes include `/`, `/_partlet/style.css`, `/_partlet/index.json`,
`/<project>`, `tree/<directory>`, `blob/<path>`, `raw/<path>`, archives
at `archive/<project>.{zip,tar.gz}`, and Git `HEAD`, `info/refs`,
`objects/info/packs` and content-addressed pack/index files. `.git` is a
project alias. GET and HEAD are supported; writes return 405 and Git
push discovery returns 403. A smart upload-pack probe receives plain
refs so Git falls back to dumb HTTP. Loose objects and alternates are
deliberately absent because the publisher emits packs only.

Paths decode once per segment. Invalid UTF-8, malformed escapes, encoded
slashes, NUL and dot segments are rejected. URL parsers can normalize
dot segments before the handler sees them; the resulting public route
still cannot address internal keys. Original Unicode and percent
characters are preserved without normalization. Directory segments join
with `/children/` in keys. `current` must contain a 16-character
lowercase hex build ID and a 40- or 64-character lowercase hex tip.
Other fields, including `previous`, do not become public keys. Locks,
current records, configuration and arbitrary keys have no route.

Pages disable scripts, forms, frames and base overrides through CSP. Raw
HTML, SVG, XML and binary files download as octet streams; text
including JavaScript is plain text; raster image extensions get image
types. Non-page responses carry a sandbox CSP with an opaque origin and
`nosniff`, including mislabeled image content. Attachment names use
encoded `filename*` values. Tests verify bytes and safety headers in
workerd, rather than making a browser execution claim.

Every object has an ETag. GET/HEAD support weak `If-None-Match` lists
and `*`, with strong `If-Match` checked first (412 on failure). Date
validators are ignored; no Last-Modified validator is emitted. Pack and
index GET requests support one `bytes=N-[M]` range. Unsatisfiable ranges
return 416; unsupported forms return the full object. If-Range requires
the matching strong ETag, otherwise the full object is sent. Range is
ignored for HEAD and other object types. Errors are generic and never
include bucket keys or provider exception details.

## Cache and publication retention limit

Only content-addressed packs and indexes are immutable for one year.
Mutable Git metadata (`HEAD`, `info/refs`, `objects/info/packs`) uses
`no-store` so independent cache ages cannot pair new refs with a pack
list that lacks their objects. Stable site URLs, including raw files and
archives resolved through `current`, use `public, max-age=60` and ETags.
Errors use `no-store`. No Workers Cache API or edge cache rules are
configured here.

The publisher retains pack/index objects for at least an hour from the
first sweep that observes them outside both live and previous pack
lists. Persisted retirement times survive interrupted and unchanged
runs. This keeps A's advertised objects available when B and C
consolidate rapidly, covering legacy 60-second metadata freshness plus
59 minutes of fetch time. A longer pause may require a fresh fetch;
explicit unpublish invalidates all project URLs immediately. Explicitly
approved rewrites change the advertised snapshot and clients racing them
may need a fresh fetch. Site/archive objects retain their existing
one-publication grace. See the
[publisher contract](../docs/PUBLISHING.md) for expiry, orphan cleanup
and clock behavior.

`bash scripts/e2e.sh` proves the rapid-publication case locally: cache
A's public metadata, consolidate B and C, then clone A through the
Worker's public object routes and pull the latest export normally. A
cache that obeys response headers separately verifies a fresh clone
cannot combine the old pack list with new refs. It also covers actual
review/publish/unpublish commands against loopback S3, mirrored exactly
into local R2. Hosted S3/binding coherence, edge caching and browser
execution remain separate user-run acceptance checks.

For an existing deployment, deploy the new Worker first and wait for all
old 60-second Git metadata cache entries to expire before a rapid
publish. `no-store` cannot invalidate entries already served by the old
Worker.

## Development

Use Node from [.node-version](.node-version), npm >=11.19, Python 3.12,
`uv`, Git and shellcheck. Each worktree gets its own `.venv`. npm's
`allowScripts` permits only the pinned esbuild and workerd installers.
Setup rejects older npm versions, which ignore that allowlist.

From the repository root:

```bash
bash scripts/setup.sh
bash scripts/check.sh
```

The Worker gates are `worker-lint`, `worker-typecheck`, `worker-test`,
`worker-bundle` and `worker-smoke` under `scripts/`. Lint also checks
the Python smoke driver. Types are generated and checked with Wrangler:

```bash
cd worker
WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false npm run types
node_modules/.bin/biome check --write .
```

The runtime suite uses workerd and simulated R2. The bundle gate runs
`wrangler deploy --dry-run` only. The smoke gate builds a synthetic
monorepo with the actual publisher, seeds isolated local R2, starts
`wrangler dev --local`, clones, publishes a second commit and pulls it.
It checks directory keys, unusual names, archives, raw safety headers
and real pack ranges. It reserves a local port and owns its temporary
Git configuration, HOME, storage and server processes; no account is
needed. A failed run prints its local server log.

Local commands disable metrics and Cloudflare's default metadata fetch
with `WRANGLER_SEND_METRICS=false` and
`CLOUDFLARE_CF_FETCH_ENABLED=false`. Local bindings alone do not disable
that tool-default metadata request.

The
[Workers Vitest configuration](https://developers.cloudflare.com/workers/testing/vitest-integration/configuration/)
and
[R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)
document the external runtime interfaces used here.
