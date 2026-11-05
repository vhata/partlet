# Publish your first site

This guide connects a GitHub source repository to a public Partlet site.
First complete the README's
[install, configure, and review steps](../README.md#get-started). You
should have a local Partlet checkout, a source repository containing
`partlet.toml` with an approved project, and these shell variables:

```bash
PARTLET_DIR=/absolute/path/to/partlet
SOURCE_REPO=/absolute/path/to/my-monorepo
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
Node version manager, with npm >=11.19. From any directory:

```bash
cd "$PARTLET_DIR"
npm ci --prefix worker --no-audit --no-fund
git rev-parse HEAD
```

Record that full Partlet commit hash. Use the same reviewed commit for
the GitHub Action in step 4, so the local reviewer, publisher, and
Worker come from the same version. You do not need to create release
tags or fork Partlet to use it. Keep your deployment configuration
locally and preserve it when updating your checkout.

## 2. Create storage and deploy the public site

Your site needs a public address. You can use Cloudflare's default
`workers.dev` address without owning a domain, or a hostname on a domain
you own. Choose one of the configurations below before deploying.

From the Partlet checkout, log in and confirm the account:

```bash
cd "$PARTLET_DIR/worker"
node_modules/.bin/wrangler login
node_modules/.bin/wrangler whoami
```

Create the bucket, or use an existing dedicated bucket and skip this
command:

```bash
node_modules/.bin/wrangler r2 bucket create my-partlet-public
```

Keep direct public bucket access disabled; visitors access it through
the Worker. Partlet manages and cleans up objects under its source
prefix, so keep unrelated files outside that prefix.

Edit [worker/wrangler.toml](../worker/wrangler.toml) in your Partlet
checkout. In either configuration, set `SOURCE` to the manifest's
`site.source` and `bucket_name` to the bucket you just created. Keep
`binding = "BUCKET"`, `main`, and the compatibility date. The default
Worker name is `partlet`; change `name` if you need to avoid replacing
an existing Worker with that name. If you have several Cloudflare
accounts, set the intended top-level `account_id` too.

### Option A: Use Cloudflare's default `workers.dev` address

In the Cloudflare dashboard, open **Workers & Pages** and find **Your
subdomain**. Choose or change it there if needed. With Worker name
`partlet` and account subdomain `my-account`, your site's address is
`https://partlet.my-account.workers.dev`. The account subdomain is
separate from your account ID and Partlet's `SOURCE`.

Remove the entire `[[routes]]` block, including `pattern` and
`custom_domain`. Set `workers_dev = true` at the top level, before
`[vars]` or any other table. Your configuration should look like this:

```toml
name = "partlet"
main = "src/index.ts"
compatibility_date = "2026-10-01"
workers_dev = true

[vars]
SOURCE = "my-monorepo"

[[r2_buckets]]
binding = "BUCKET"
bucket_name = "my-partlet-public"
```

Cloudflare derives this address from `name` and your account subdomain;
you do not put a `workers.dev` hostname in `pattern`. See Cloudflare's
[`workers.dev` guide](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
for account subdomain settings.

### Option B: Use a hostname on your own domain

Choose a hostname such as `code.example.com` under a domain already
active in your Cloudflare account. You choose the `code` part; replace
`example.com` with your own domain. Dedicate this hostname to Partlet,
since the Worker will serve every path on it. Do not use a hostname
already serving another site or one with an existing CNAME record.

Use this configuration, replacing `code.example.com` with that hostname:

```toml
name = "partlet"
main = "src/index.ts"
compatibility_date = "2026-10-01"
workers_dev = false

[vars]
SOURCE = "my-monorepo"

[[r2_buckets]]
binding = "BUCKET"
bucket_name = "my-partlet-public"

[[routes]]
pattern = "code.example.com"
custom_domain = true
```

The last three lines tell Cloudflare where to serve the site:

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
not select a `workers.dev` address. Use Option A for that.
`workers_dev = false` here disables the additional default address.
Cloudflare's
[Custom Domains guide](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
explains hostname requirements and DNS/certificate setup.

### Deploy and record your site's URL

Deploy from `worker/` after checking those choices:

```bash
WRANGLER_SEND_METRICS=false node_modules/.bin/wrangler deploy
```

Wrangler prints the deployed URL. You can also find it by opening your
Worker in Cloudflare under **Settings → Domains & Routes**. Confirm that
address and its R2 binding. In your source repository's `partlet.toml`,
set `site.base_url` to that full HTTPS URL, for example
`https://partlet.my-account.workers.dev` for Option A or
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
[R2 token guide](https://developers.cloudflare.com/r2/api/tokens/). Also
copy the Cloudflare account ID from the dashboard.

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

Copy the supplied workflow into your **source repository**:

```bash
mkdir -p "$SOURCE_REPO/.github/workflows"
cp "$PARTLET_DIR/examples/partlet.yml" \
  "$SOURCE_REPO/.github/workflows/partlet.yml"
```

Edit that copy:

- Replace `PARTLET_RELEASE_SHA` in `uses: vhata/partlet@...` with the
  full Partlet commit hash recorded in step 1. It is the Partlet code
  version, separate from your project's generated `approved` hash.
- Replace `SOURCE` in `group: partlet-SOURCE` with `my-monorepo`.
- If your publishing branch differs, replace `main` in `branches` with
  the manifest's `site.branch`.

Keep the full-history checkout (`fetch-depth: 0`), read-only workflow
permissions, `persist-credentials: false`, and
`cancel-in-progress: false`. Use this same concurrency group in any
other workflows publishing the same source. Publish on branch pushes,
rather than pull requests. The Action installs its own tools on the
Linux runner; you do not need an installation step in this workflow.

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
