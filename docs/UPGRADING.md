# Upgrading Partlet

Use this guide to update an installed Partlet and its published sites.
For a new installation, follow [installation](INSTALLATION.md) and
[first-site setup](GETTING_STARTED.md).

## Upgrade a site

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

Use [Configure your site](SITE.md) and the
[example manifest](../examples/partlet.toml) to choose the name, tagline
and optional homepage file before previewing and republishing.

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
