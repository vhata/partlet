# Install Partlet and keep your own configuration

Partlet installs as a command-line application. Its installation holds
the publisher and packaged Worker code; your source repository holds
`partlet.toml`; your deployment directories hold your own Wrangler
configuration. You do not edit files in the Partlet checkout to use it.

For an existing installation, see [Upgrading Partlet](UPGRADING.md).

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

## Site configuration

Keep `partlet.toml` in your source repository. Set the storage namespace
and public URL, then choose the site's display name and optional footer
text:

```toml
[site]
source = "personal"
base_url = "https://code.example.com"
name = "My projects"
tagline = "Tools and experiments"
# readme = "public/home.md"
```

Without `name`, the header uses the public URL's hostname. Without
`tagline`, the footer has no tagline. To add an introduction above the
project list, set `readme` to a Markdown file committed on the
publishing branch. No README is selected automatically.

Selecting a homepage file authorizes its publication independently of
project approvals. It is not secret-scanned, including with `--scan`;
review its contents before selecting it and before publishing changes.
See the [homepage policy](PUBLISHING.md#site-identity-and-homepage) for
file and link requirements, and the
[manifest reference](PUBLISHING.md#manifest-reference) for project
selection and other settings. Follow
[first-site setup](GETTING_STARTED.md) to connect this configuration to
hosting and publication.

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

## Removing the installed command

`uv tool uninstall partlet` removes the Python application and command.
It leaves Partlet's downloaded tool cache, your source repositories,
deployment directories, cloud resources and public data in place.
Uninstalling the tool does not unpublish any project.
