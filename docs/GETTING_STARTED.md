# Publish your first site

This guide connects a GitHub source repository to a public Partlet site.
First complete the README's
[install, configure, and review steps](../README.md#get-started). You
should have `partlet` on your PATH, a source repository containing
`partlet.toml` with an approved project, and these shell variables:

```bash
SOURCE_REPO=/absolute/path/to/my-monorepo
PARTLET_SITE="$HOME/partlet-sites/personal"
# The full reviewed Partlet commit used for your installation:
PARTLET_REV=REPLACE_WITH_FULL_COMMIT_HASH
```

The examples use source name `my-monorepo`, project `foo`, publishing
branch `main`, bucket `my-partlet-public`, and site
`https://code.example.com`. Substitute your choices consistently:

| Choice | Where it must match |
| -- | -- |
| `my-monorepo` | Manifest `site.source`, Worker `SOURCE`, workflow concurrency suffix |
| `my-partlet-public` | Worker `bucket_name`, GitHub `PARTLET_R2_BUCKET` secret |
| `code.example.com` | Example site hostname; use your chosen `workers.dev` or custom hostname in manifest `base_url` and all URLs below |
| `main` | Manifest `site.branch`, workflow push branch |

R2 storage and Worker hosting are **billable**. The commands below are
for you to run in your own account; they create a bucket and deploy a
Worker at your chosen public address. You can start with a harmless
demonstration project before exposing real history.

## 1. Install the deployment tools

Install the Node version listed in
[worker/.node-version](../worker/.node-version) using your preferred
Node version manager, with npm >=11.19. Node 24 or newer is required;
the pinned version is recommended. From any directory:

```bash
partlet setup --worker
```

Use the same reviewed Partlet commit for the GitHub Action in step 4, so
the local reviewer, publisher, and Worker come from the same version.
You do not need to create release tags or fork Partlet to use it. Setup
downloads the pinned scanner and installs the packaged npm lockfile in
Partlet's user-data directory. It does not deploy anything or edit a
Partlet checkout.

## 2. Create storage and deploy the public site

Your site needs a public address. You can use Cloudflare's default
`workers.dev` address without owning a domain, or a hostname on a domain
you own. Choose one of the configurations below before deploying.

Log in and confirm the account:

```bash
partlet worker login
partlet worker whoami
```

`whoami` prints your account names and IDs. Copy the ID of the account
you want to use into a shell variable:

```bash
PARTLET_ACCOUNT_ID=REPLACE_WITH_YOUR_32_CHARACTER_ACCOUNT_ID
```

Use this account explicitly when creating your configuration below. If
R2 is not enabled yet, activate it in the Cloudflare dashboard and
accept its billing terms first. The remaining bucket and Worker setup
can run from your terminal.

Keep direct public bucket access disabled; visitors access it through
the Worker. Partlet manages and cleans up objects under its source
prefix, so keep unrelated files outside that prefix.

Create a deployment directory outside the Partlet installation. Choose
one of the address options below. Both produce your own
`$PARTLET_SITE/wrangler.toml`; Partlet supplies the installed Worker
code, so you do not add a `main` path.

Use a Worker name that will not replace an unrelated Worker. If you have
several Cloudflare accounts, select the intended ID above. The
`--account-id` option records it in the generated file. Keep the
compatibility date. `SOURCE` must match the manifest's `site.source`,
and `bucket_name` must name the bucket you will use.

### Option A: Use Cloudflare's default `workers.dev` address

You do not need to look up an account subdomain before creating the
configuration. Deployment uses your account's existing subdomain, or
Wrangler prompts you to register one if the account has none. With
Worker name `partlet-personal` and account subdomain `my-account`, your
site's address is `https://partlet-personal.my-account.workers.dev`. The
account subdomain is separate from your account ID and Partlet's
`SOURCE`.

```bash
partlet worker init "$PARTLET_SITE" \
  --name partlet-personal --source my-monorepo \
  --bucket my-partlet-public --workers-dev \
  --account-id "$PARTLET_ACCOUNT_ID"
```

This sets top-level `workers_dev = true` and omits the `[[routes]]`
block. Cloudflare derives the address from the Worker name and account
subdomain; you do not put a `workers.dev` hostname in `pattern`. See
Cloudflare's
[CLI deployment guide](https://developers.cloudflare.com/workers/get-started/guide/#4-deploy-your-project)
for first-time registration. Changing an existing account subdomain
affects other Workers too; it is not part of Partlet setup.

### Option B: Use a hostname on your own domain

Choose a hostname such as `code.example.com` under a domain already
active in your Cloudflare account. You choose the `code` part; replace
`example.com` with your own domain. Dedicate this hostname to Partlet,
since the Worker will serve every path on it. Do not use a hostname
already serving another site or one with an existing CNAME record.

```bash
partlet worker init "$PARTLET_SITE" \
  --name partlet-personal --source my-monorepo \
  --bucket my-partlet-public --domain code.example.com \
  --account-id "$PARTLET_ACCOUNT_ID"
```

The generated configuration includes:

```toml
[[routes]]
pattern = "code.example.com"
custom_domain = true
```

These lines tell Cloudflare where to serve the site:

- `[[routes]]` adds an address for the Worker. The double brackets are
  TOML syntax for an entry in a list; one hostname needs one entry.
- `custom_domain = true` tells Cloudflare to connect that hostname
  directly to the Worker and manage its DNS record and HTTPS
  certificate. All paths on the hostname go to this Worker.
- `pattern` is Cloudflare's shared field name for routing addresses.
  **With `custom_domain = true`, its value is one exact hostname**:
  `code.example.com`, with no `https://`, path, trailing slash, or `*`.
  In Cloudflare's other routing mode, this field can hold a wildcard URL
  pattern such as `example.com/*`, which is why it has that name.

Setting `custom_domain = false` selects that other routing mode; it does
not select a `workers.dev` address. Use Option A for that. The generated
`workers_dev = false` disables the additional default address.
Cloudflare's
[Custom Domains guide](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
explains hostname requirements and DNS/certificate setup.

### Create the bucket

After choosing either address option, create the configured R2 bucket:

```bash
partlet worker bucket-create --config "$PARTLET_SITE/wrangler.toml"
```

The command shows the account ID and bucket name, explains that R2 is
billable, and asks for confirmation before creating it. It uses
[Wrangler's bucket creation command](https://developers.cloudflare.com/r2/buckets/create-buckets/)
with your existing Cloudflare login; no publisher keys are needed yet.
The new bucket is private by default. Skip this command if you already
have a dedicated bucket with that name in the selected account.
Deployment itself does not automatically provision missing buckets.

### Deploy and record your site's URL

Review `$PARTLET_SITE/wrangler.toml`. This directory belongs to you and
can live in your own configuration repository. Its generated
`.gitignore` excludes local runtime state. Create another directory with
a different Worker name and public address for another site. Every
command explicitly selects its configuration.

Check the local bundle, then deploy after checking those choices:

```bash
partlet worker deploy --config "$PARTLET_SITE/wrangler.toml" --dry-run
partlet worker deploy --config "$PARTLET_SITE/wrangler.toml"
```

The real deployment identifies its billable target and asks for
confirmation. A dry run bundles locally and does not deploy. Installed
tool upgrades preserve this config; upgrading the hosted Worker requires
an explicit deployment. See [upgrades](UPGRADING.md#upgrade-a-site).

Wrangler prints the deployed URL and R2 binding in the terminal. Check
that they match your choices. In your source repository's
`partlet.toml`, set `site.base_url` to that full HTTPS URL, for example
`https://partlet-personal.my-account.workers.dev` for Option A or
`https://code.example.com` for Option B. This is the URL Partlet puts in
pages and clone links. Use it wherever the rest of this guide shows
`https://code.example.com`.

The site has no content until the first publish; a 404 at this point is
expected. For an upgrade from an older deployment, wait at least 60
seconds after deploying before publishing so old cached Git metadata can
expire.

## 3. Give the publisher access to its bucket

In Cloudflare R2, create an API credential with **Object Read & Write**
access scoped to this bucket only. Save its Access Key ID and Secret
Access Key when shown; these are the R2 S3 credentials described in
Cloudflare's
[R2 token guide](https://developers.cloudflare.com/r2/api/tokens/). Use
the account ID you recorded from `partlet worker whoami` in step 2.

This credential step still uses the dashboard. Cloudflare supports
[creating tokens through its API](https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/),
but requires a separate initial token with permission to create other
tokens. The normal Wrangler login does not provide that authority.
Creating one bucket-scoped credential directly avoids granting that
broader permission for a single site.

In your **source repository** on GitHub, open **Settings → Secrets and
variables → Actions**, then add these repository secrets:

| Secret | Value |
| -- | -- |
| `PARTLET_R2_ACCOUNT_ID` | Your Cloudflare account ID |
| `PARTLET_R2_ACCESS_KEY_ID` | The R2 Access Key ID |
| `PARTLET_R2_SECRET_ACCESS_KEY` | The R2 Secret Access Key |
| `PARTLET_R2_BUCKET` | `my-partlet-public` |

If you use the GitHub CLI, these commands prompt for each value without
putting it in shell history. Replace `OWNER/MONOREPO`:

```bash
gh secret set PARTLET_R2_ACCOUNT_ID --repo OWNER/MONOREPO
gh secret set PARTLET_R2_ACCESS_KEY_ID --repo OWNER/MONOREPO
gh secret set PARTLET_R2_SECRET_ACCESS_KEY --repo OWNER/MONOREPO
gh secret set PARTLET_R2_BUCKET --repo OWNER/MONOREPO
```

The Worker uses its bucket binding, so do not give it these write keys.
Wrangler's account login and the publisher's R2 credentials serve
different purposes. Keep credentials out of Git and job-level `env`.

## 4. Add the publishing workflow

Download the supplied workflow at your installed revision into your
**source repository** (or copy `examples/partlet.yml` if you kept the
Partlet checkout):

```bash
mkdir -p "$SOURCE_REPO/.github/workflows"
curl --fail --show-error --location \
  "https://raw.githubusercontent.com/vhata/partlet/$PARTLET_REV/examples/partlet.yml" \
  --output "$SOURCE_REPO/.github/workflows/partlet.yml"
```

The file describes a GitHub Actions workflow with two steps, run in
order:

1. `uses: actions/checkout@...` downloads your **source repository**
   onto the runner, including its Git history and `partlet.toml`.
1. `uses: vhata/partlet@...` publishes the approved projects from that
   checkout to R2. It installs Partlet's tools on the Linux runner, so
   you do not need a separate installation step.

Each step's indented `with:` block supplies inputs to that step's
action. **`fetch-depth` and `persist-credentials` belong under
`actions/checkout`, where the example already puts them.** The
`vhata/partlet` step's separate `with:` block supplies the R2
credentials and bucket from your GitHub secrets.

Make these three substitutions in the copy. The example marks them with
`EDIT` comments:

| Location in the workflow | What to edit |
| -- | -- |
| `on` → `push` → `branches` near the top | Replace `main` if your manifest's `site.branch` differs. |
| Top-level `concurrency` → `group` | Replace `SOURCE` in `partlet-SOURCE` with your manifest's `site.source`, for example `partlet-my-monorepo`. |
| Second step, `uses: vhata/partlet@PARTLET_RELEASE_SHA` | Replace `PARTLET_RELEASE_SHA` with the full Partlet commit hash recorded in step 1. This selects Partlet's code version; it is separate from your project's generated `approved` hash. |

The remaining settings are already configured. Keep them in these
locations:

| Location in the workflow | Setting | Purpose |
| -- | -- | -- |
| First step, `actions/checkout` → `with` | `fetch-depth: 0` | Downloads the full Git history Partlet needs to export projects. |
| First step, `actions/checkout` → `with` | `persist-credentials: false` | Keeps checkout's GitHub token out of the Git credentials available to later steps. |
| Top-level `permissions` | `contents: read` | Gives the workflow's GitHub token read-only access to repository contents. R2 access comes from the separate publishing credentials. |
| Top-level `concurrency` | `cancel-in-progress: false` | Lets an active publication finish when another run is queued. |

Use this same concurrency group in any other workflows publishing the
same source. Publish on branch pushes, rather than pull requests.

For a jurisdiction-specific bucket, set the Action's optional `endpoint`
input to its matching S3 endpoint. Further options are in the
[Action reference](PUBLISHING.md#github-action).

Commit `partlet.toml` (including the `approved` hash) and the workflow
on your publishing branch, then push. If your repository requires pull
requests, merge those files through your usual process. For example, on
a repository where direct pushes are allowed:

```bash
git -C "$SOURCE_REPO" switch main
git -C "$SOURCE_REPO" add partlet.toml .github/workflows/partlet.yml
git -C "$SOURCE_REPO" commit -m 'Publish foo with Partlet'
git -C "$SOURCE_REPO" push origin main
```

On GitHub, open **Actions → Partlet** and select the new run. Its job
summary lists tool versions and a result for each project. Expect
`published` for your first approved project. `skipped` is not a
publication: check that the committed manifest contains its approval. A
failed scan or history check explains why publication was blocked.

## 5. Check the result

Open `https://code.example.com/` and follow the `foo` link. Browse a
directory and file, try a raw download, and download an archive. From a
directory outside your source checkout:

```bash
git clone https://code.example.com/foo partlet-public-check
git -C partlet-public-check log -1 --oneline
```

Check that the clone contains only the intended project's files and
history. Make and push a harmless change inside the source project's
directory. After its Partlet run succeeds:

```bash
git -C partlet-public-check pull --ff-only
git -C partlet-public-check log -1 --oneline
```

Confirm the expected change arrived. Later fast-forward changes use this
same automatic path without another approval. An unchanged run reports
`unchanged`. If a macOS clone hangs, use the
[Git troubleshooting guide](PUBLISHING.md#macos-clone-hangs-over-http2).

For deeper deployment verification, inspect responses with `curl`:

```bash
curl --fail --show-error --head https://code.example.com/foo/info/refs
curl --fail --show-error https://code.example.com/foo/objects/info/packs
curl --fail --show-error -o /tmp/partlet-foo.zip \
  https://code.example.com/foo/archive/foo.zip
unzip -t /tmp/partlet-foo.zip
```

Git metadata must carry `Cache-Control: no-store`; avoid Cloudflare
cache rules that override the Worker's response policy. Local tests and
CI use simulated services, so these deployed clone, pull, browser, and
binding checks are your confirmation that your account setup works.

For adding projects, moving directories, removing public content, or
recovering a stopped publisher, continue with the
[publishing reference](PUBLISHING.md).
