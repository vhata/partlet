# Install Partlet and keep your own configuration

Partlet installs as a command-line application. Its installation holds
the publisher and packaged Worker code; your source repository holds
`partlet.toml`; your deployment directories hold your own Wrangler
configuration. You do not edit files in the Partlet checkout to use it.

## Prerequisites

- macOS or Linux, Git 2.31 or newer, and
  [uv](https://docs.astral.sh/uv/getting-started/installation/).
- For Worker preview or deployment, Node 24 or newer and npm >=11.19.
  The recommended Node version is in
  [worker/.node-version](../worker/.node-version). Use your preferred
  Node version manager. Older npm versions do not enforce the
  install-script allowlist and are refused.

The installer uses uv to provide an isolated Python 3.12 application. It
does not install uv, replace system Python or Node, or install Git
hooks. Worker tooling is unnecessary for reviewing and publishing
exports.

## From a checkout

From the Partlet checkout:

```bash
PARTLET_REV="$(git rev-parse HEAD)"
bash scripts/install.sh
```

This installs `partlet` on your PATH, the checksum-pinned gitleaks
scanner, and the lockfile-pinned npm tools. Use
`bash scripts/install.sh --publisher-only` if you do not need Worker
tools yet. You can prepare them later with `partlet setup --worker`.

Record the full `PARTLET_REV` value for the matching GitHub Action. The
install copies the application and assets; it is not editable and does
not depend on retaining the checkout. If `partlet` is not on your
shell's PATH, run `uv tool update-shell` and restart your shell.

## Directly from GitHub

Choose a full reviewed Partlet commit hash and substitute it below:

```bash
PARTLET_REV=REPLACE_WITH_FULL_COMMIT_HASH
uv tool install --python 3.12 \
  "git+https://github.com/vhata/partlet.git@$PARTLET_REV"
partlet setup --worker
```

Use `partlet setup` instead of `partlet setup --worker` for publisher
tools only. uv manages the Python application; explicit setup prepares
Partlet's additional tools. Normal review, preview, build and Worker
commands do not download missing dependencies automatically.

To browse a source repository without setting up hosting, run
`partlet preview --repo /absolute/path/to/source` after
`partlet setup --worker`. Open `http://127.0.0.1:8787/`; no deployment
directory or approval is required. See the
[local preview guide](../worker/README.md#preview-your-site).

## From a wheel

If you have a Partlet wheel built from a reviewed revision:

```bash
uv tool install --python 3.12 /absolute/path/to/partlet-0.1.0-py3-none-any.whl
partlet setup --worker
```

The package includes the Worker source, npm lockfile, preview seeder and
scanner installer. A source checkout is not required at runtime. Use the
commit associated with that build for your GitHub Action. These
instructions do not imply a published PyPI package or release download.

## Deployment directories

Create as many configuration directories as you need:

```bash
partlet worker init "$HOME/partlet-sites/personal" \
  --name partlet-personal --source personal \
  --bucket personal-public --domain code.example.com
partlet worker init "$HOME/partlet-sites/work" \
  --name partlet-work --source work \
  --bucket work-public --domain code.work.example
```

If you do not own a domain, replace `--domain HOSTNAME` with
`--workers-dev`. The generated config enables Cloudflare's default
address and has no custom-domain route. See the
[public address options](GETTING_STARTED.md#2-create-storage-and-deploy-the-public-site).

`init` writes `wrangler.toml` and a `.gitignore` for local state. It
does not create cloud resources. It refuses to replace an existing
configuration. You can omit options and edit the generated placeholders;
deployment refuses placeholders. Set `account_id` or pass `--account-id`
when you need to select a specific Cloudflare account.

To create a new bucket, set `account_id` explicitly (or pass
`--account-id` to `init`), then run:

```bash
partlet worker bucket-create --config "$HOME/partlet-sites/personal/wrangler.toml"
```

Bucket creation is a separate billable action and asks for confirmation.
It uses the bucket and account in that file and leaves direct public
access disabled for a newly created bucket. Skip creation for an
existing bucket. Deployment does not create buckets automatically. See
[first-site setup](GETTING_STARTED.md) for the full sequence.

Each source name must match its source repository's `site.source`. Each
public address must match that repository's `base_url`. Choose distinct
Worker names and addresses for independent deployments. Keep bucket and
source prefixes separate when you need independent publication data.

Select the configuration explicitly, from any working directory:

```bash
partlet worker deploy \
  --config "$HOME/partlet-sites/personal/wrangler.toml" --dry-run
```

Partlet supplies the installed Worker entry point. The config does not
need a `main` path, installation path or checkout path. The supported
configuration describes a single Worker with a `SOURCE` variable, one
`BUCKET` R2 binding, and custom-domain routes or a `workers.dev`
address. Arbitrary build hooks, extra bindings and Wrangler environments
are outside this interface.

You may track these configuration directories in your own repository.
Keep access tokens and R2 write keys out of them. Cloudflare login and
publisher credentials keep their existing separate roles; see
[first-site setup](GETTING_STARTED.md).

## Dependency storage

Partlet stores downloaded tools below its user-data directory:

- macOS: `~/Library/Application Support/partlet`.
- Linux: `${XDG_DATA_HOME:-~/.local/share}/partlet`.
- Either platform: set `PARTLET_DATA_DIR` to an explicit directory to
  isolate an installation, including for CI or testing.

`XDG_DATA_HOME` also overrides the default on macOS.

Use the same override for setup and subsequent commands. The directory
contains installed tools, not your deployment configs or approvals.
Worker runtimes are keyed by their packaged inputs, so different builds
can coexist. Setup reuses complete installations and does not treat a
failed npm install as usable. Older tool caches may remain after
upgrades; they do not select or change your deployment target.

## Upgrades

Choose a new reviewed revision, then rerun `bash scripts/install.sh`
from that checkout. For a direct Git installation:

```bash
PARTLET_REV=REPLACE_WITH_NEW_FULL_COMMIT_HASH
uv tool install --reinstall --python 3.12 \
  "git+https://github.com/vhata/partlet.git@$PARTLET_REV"
partlet setup --worker
```

Updating the installed application and preparing its dependencies does
not rewrite your Wrangler configs, manifests, approvals or GitHub
workflow. It does not deploy a Worker or regenerate published pages. For
each existing site:

1. Read the migration notes below and prepare any required source
   changes. Run `partlet preview --repo /path/to/source` with the
   updated publisher.
1. Check the Worker bundle with
   `partlet worker deploy --config /path/to/wrangler.toml --dry-run`.
   Deploy explicitly with the same command without `--dry-run`, using
   the site's existing configuration. Worker deployment changes a
   billable Cloudflare service; the dry run does not deploy it.
1. Wait at least 60 seconds so legacy Git metadata cache entries can
   expire, then update the GitHub Action's Partlet commit pin to the
   same reviewed revision, if the site uses the Action.
1. Run the normal publishing workflow, or run
   `partlet publish --repo /path/to/source` with the site's R2
   credentials. Check that every intended project reports `published` or
   `unchanged`; investigate `failed` or `skipped` results before calling
   the upgrade complete.

Keep the existing buckets, domains, manifest source prefixes and
approval pins. Installing Partlet and deploying its Worker leave stored
project pages unchanged until publication. Renderer or theme changes
rebuild pages automatically on publication, even without new project
commits; they do not change exported history or require renewed history
approval.

### Semantic output version 1 migration

This release introduces semantic output version 1 and theme format 2.
The bundled Classic, Paper and Terminal themes need no manifest changes.
For a vendored theme, adapt its CSS to the
[format-2 contract](THEMES.md#write-a-theme), set its `theme.toml`
`format_version` to `2`, and commit the changes on the publishing
branch. Changing only the version number does not establish
compatibility. Run `partlet theme check --repo /path/to/source` and
preview before publishing. Format-1 packs are rejected before
publication writes.

Complete a successful publication with the updated Partlet before using
its `unpublish` command on an existing site. Publication writes the new
stored theme metadata needed to rebuild the index without source files.
The new removal command rejects old stored theme metadata before
deleting project data; if it reports `invalid stored site theme`,
publish with the updated version first, then retry removal. Do not
delete stored metadata or recreate the bucket to work around that check.

### Site identity and homepage

Site identity and homepage support require updating the publisher/Action
and republishing. Existing sites default to their public URL hostname
and an empty tagline, with no homepage introduction. This renderer
revision regenerates pages without new export approval. Publish
successfully to persist identity and homepage metadata before
source-free removal. When that metadata is absent, removal uses the
manifest identity and no introduction. Malformed metadata stops removal
before deleting live state; repair it by publishing successfully. Output
version 1 and theme format 2 retain their existing meanings; no format-1
theme adapter is provided.

## Moving from the checkout-based instructions

Copy your edited `worker/wrangler.toml` to a deployment directory you
own, then remove its `main = "src/index.ts"` line. Keep the Worker name,
account, source, bucket, domain and compatibility date. You do not need
to recreate the bucket or change your source manifest or approvals. The
wrapper supplies the installed entry point and validates the config.

Run `partlet setup --worker`, then check the copied config with
`partlet worker deploy --config /path/to/wrangler.toml --dry-run`. Keep
your old checkout and configuration until you have verified the new
installation. The migration does not require a cloud deployment.

## Removing the installed command

`uv tool uninstall partlet` removes the Python application and command.
It leaves Partlet's downloaded tool cache, your source repositories,
deployment directories, cloud resources and public data in place.
Uninstalling the tool does not unpublish any project.
