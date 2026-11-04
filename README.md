# Partlet

Publish selected directories of a private Git monorepo as public,
read-only Git repositories and a browsable site. The publisher exports
and scans project history; the Cloudflare Worker serves public objects
from R2 without access to the private repository or publisher keys.

## Publishing a monorepo

The source repository carries `partlet.toml`, a publishing workflow, and
four GitHub Actions secrets. Partlet and its dependencies come from the
Action checkout selected by the workflow's release commit SHA.

A minimal manifest for a project in `tools/foo` is:

```toml
[site]
source = "my-source"
base_url = "https://partlet.example.com"
branch = "main"

[projects.foo]
path = "tools/foo"
description = "Foo command-line tool"
```

Copy [examples/partlet.yml](examples/partlet.yml) to
`.github/workflows/partlet.yml` in the source repository. Replace
`SOURCE` with `site.source`, `PARTLET_RELEASE_SHA` with the reviewed
Action release commit, and `main` if using another publishing branch.
Keep `fetch-depth: 0`, `persist-credentials: false`, read-only workflow
permissions, and `cancel-in-progress: false`. All workflows publishing
the same source must use the same concurrency group. Avoid pull-request
triggers: publication requires HEAD at the publishing branch tip and an
exactly committed manifest. The source lock also covers publishers
outside this workflow and never expires automatically.

Before publishing, use a separate Partlet checkout with Python 3.12,
`uv`, Git, shellcheck, and the Node/npm versions in the
[Worker guide](worker/README.md):

```bash
bash scripts/setup.sh
.venv/bin/partlet review foo --repo /absolute/path/to/source \
  --published-tip none
```

Inspect the report's complete history, deleted files, identities,
messages and secret scan before answering yes. The command writes the
exported commit as `approved` in `partlet.toml`. Commit and push that
pin on the publishing branch. For an existing public project, omit
`--published-tip none` so review reads its public refs. Approval never
bypasses scanning or fast-forward enforcement. See
[Publisher contracts](docs/PUBLISHING.md) for path moves, rewrites,
scanner configuration, summaries and recovery.

## Action contract

The composite Action supports Linux x64 and ARM64 runners. Use
`ubuntu-24.04` in the consumer workflow. It installs Python 3.12, a
checksum-verified uv 0.13.5 and gitleaks 8.30.1, and hash-locked wheels
including git-filter-repo 2.47.0. The selected Action checkout supplies
Partlet's code; no package build backend or source repository code is
installed. The isolated Python launcher excludes the source checkout and
clears inherited Python import configuration before child tools. Setup
runs in the Action directory with uv configuration and caches disabled.
Git comes from the runner image; actual versions are recorded in the
step summary rather than claimed identical across runner updates.

Inputs `account-id`, `access-key-id`, `secret-access-key` and `bucket`
come from the four secrets in the example. Only the publishing step
receives them. Do not put credentials in job-level `env`. Optional
`endpoint` supports an R2 jurisdiction endpoint; `repo` defaults to `.`,
and `manifest` defaults to `partlet.toml` relative to that checkout.
`local-out` is a test mode: it scans and builds into a local store while
applying the same committed-manifest and checkout requirements. A
detached checkout is supported if it is the publishing tip: the Action
creates a missing local branch from `origin/<branch>` without fetching
or changing an existing branch. Shallow history is rejected.

## User-run first-use steps

These operations belong to the user. R2 bucket creation and Worker
provisioning/deployment are **billable**. Local checks do not perform
these steps or establish hosted behavior.

1. After the implementation PRs have landed, check out the reviewed
   Partlet release commit and run `bash scripts/setup.sh`. Review the
   [Worker deployment instructions](worker/README.md#user-run-deployment).

1. Authenticate Wrangler yourself. From `worker/`, create the bucket
   with `node_modules/.bin/wrangler r2 bucket create YOUR_BUCKET`, or
   select an existing bucket. Keep its public bucket access disabled.
   Set `bucket_name`, `SOURCE`, and the custom-domain route in
   `worker/wrangler.toml` to your bucket, manifest source and domain.

1. In Cloudflare R2, create a publisher API credential with **Object
   Read & Write**, scoped to that bucket only. Record the access key ID
   and secret when created. The Worker uses its R2 binding and must not
   receive this write credential. See Cloudflare's
   [R2 token guide](https://developers.cloudflare.com/r2/api/tokens/).

1. Review the account and binding choices, then deploy from `worker/`:

   ```bash
   WRANGLER_SEND_METRICS=false node_modules/.bin/wrangler deploy
   ```

   For an existing site, allow previously cached 60-second Git metadata
   to expire after deploying the new Worker and before publishing again.
   New metadata responses use `no-store`; pack retention separately
   protects in-flight fetches.

1. Set the source repository secrets. Each command prompts for the value
   so it stays out of shell history:

   ```bash
   gh secret set PARTLET_R2_ACCOUNT_ID --repo OWNER/MONOREPO
   gh secret set PARTLET_R2_ACCESS_KEY_ID --repo OWNER/MONOREPO
   gh secret set PARTLET_R2_SECRET_ACCESS_KEY --repo OWNER/MONOREPO
   gh secret set PARTLET_R2_BUCKET --repo OWNER/MONOREPO
   ```

   If Partlet is private, allow the source repository to use its Action
   in Partlet's Settings > Actions > General > Access. Match the
   optional `endpoint` input to a jurisdiction bucket when applicable.

1. Release only the reviewed, merged commit. For a first release, in the
   Partlet checkout, replacing `REVIEWED_RELEASE_SHA` with its SHA:

   ```bash
   git tag -a v1.0.0 REVIEWED_RELEASE_SHA -m 'Partlet Action v1.0.0'
   git push origin v1.0.0
   git tag -a v1 REVIEWED_RELEASE_SHA -m 'Partlet Action v1'
   git push origin v1
   ```

   Set `PARTLET_RELEASE_SHA` in the consumer example to that exact
   commit. Future tag moves are a separate user release decision.

1. Start with a synthetic public project on the deployed site. Then
   review each real project's full exported history locally, approve,
   commit the manifest and consumer workflow, and push the publishing
   branch. Inspect the Action summary and verify its tools and outcomes.

   If cloning hangs on macOS, see the
   [verified Git upgrade and temporary HTTP/1.1 workaround](docs/PUBLISHING.md#macos-clone-hangs-over-http2).
   The upgraded Homebrew client passed plain HTTP/2 clone and
   incremental pull without client configuration.

## Live acceptance, run by the user

After a successful publication, replace the URL and project below:

```bash
public_site=https://partlet.example.com
project=foo
git clone "$public_site/$project" partlet-live-check
curl --fail --show-error "$public_site/$project/info/refs"
curl --fail --show-error --head "$public_site/$project/objects/info/packs"
curl --fail --show-error "$public_site/$project/objects/info/packs"
curl --fail --show-error "$public_site/$project/"
curl --fail --show-error "$public_site/$project/raw/README.md"
curl --fail --show-error -o /tmp/partlet-live.zip \
  "$public_site/$project/archive/$project.zip"
unzip -t /tmp/partlet-live.zip
```

Make and push a harmless change inside the approved project, wait for
its publishing run to succeed, then run:

```bash
git -C partlet-live-check pull --ff-only
git -C partlet-live-check log -1 --oneline
```

Confirm metadata responses carry `Cache-Control: no-store`. Confirm the
expected exported change, and open the site index, project, directory
and file pages in a browser. Verify raw-download behavior, archives, and
the deployed Worker's domain and bucket binding. Repeat an unchanged run
and check its summary. These are required live checks; local simulations
and hosted CI do not establish them.

## Publication consistency

Git metadata (`HEAD`, `info/refs`, `objects/info/packs`) uses `no-store`
to avoid mixing independent cached generations. Content-addressed packs
and indexes remain immutable. Retired packs stay available for at least
one hour after the first sweep observes them outside the live and
previous pack lists. This bounds the supported in-flight fetch window; a
fetch that outlasts it must restart. Explicit approved rewrites and
unpublish can intentionally invalidate an older history. Retired site
builds and archives keep their separate one-publication grace.

See [Publisher contracts](docs/PUBLISHING.md#serialization-and-recovery)
for durable retirement, interrupted runs, storage cost and expiry. Both
cache behavior and rapid-publication retention are tested through public
Worker routes with synthetic data. Hosted acceptance remains user-run.

## Removal and recovery

To remove a project, remove its manifest entry and push that change
first. Verify that publishing has stopped, set the scoped `PARTLET_R2_*`
environment variables locally, then run:

```bash
.venv/bin/partlet unpublish foo --repo /absolute/path/to/source
```

This prompts before deleting. For a stale lock, inspect its recorded
holder and verify that run has ended before running
`.venv/bin/partlet unlock --repo /absolute/path/to/source` and
confirming. Do not automatically retry uncertain lock deletions.
Recovery and explicit removal details are in
[Publisher contracts](docs/PUBLISHING.md).

## Development and validation

Use synthetic repositories and local simulated services:

```bash
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/e2e.sh
```

Markdown is autoformatted when committing. If the hook changes a file,
review and stage it again before retrying the commit. Run
`bash scripts/fmt-markdown.sh` to format tracked Markdown manually.

See [Quality](docs/QUALITY.md) and the [Worker guide](worker/README.md)
for checks and evidence limits. The Action dependency lock is
regenerated with
`uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.12 -o action/requirements.txt`;
review every changed version and hash. No private monorepo or cloud
credentials are needed.

## License

MIT. See [LICENSE](LICENSE).

Partlet is being built with help from
[Claude Code](https://claude.com/claude-code).
