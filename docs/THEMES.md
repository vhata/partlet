# Choose or install a site theme

Partlet themes change the appearance of your public site without
changing exported Git history. A theme applies to the project index,
file listings, README pages and highlighted source. Theme selection
lives in your source repository's `partlet.toml` and works in local
builds and the GitHub Action.

## Choose a bundled theme

Add this table to your manifest:

```toml
[site.theme]
name = "paper"
mode = "auto"
```

| Name | Appearance |
| -- | -- |
| `classic` | The familiar compact repository browser. |
| `paper` | More breathing room with serif README prose. |
| `terminal` | A monospace presentation with strong code emphasis. |

Classic, Paper and Terminal on the same synthetic project:

![Classic theme in light mode](images/themes/classic.png)

![Paper theme in light mode](images/themes/paper.png)

![Terminal theme in dark mode](images/themes/terminal.png)

`mode` is `auto`, `light`, or `dark`. Auto follows the visitor's browser
color preference without JavaScript. There is no visitor toggle or
per-project theme. With no `[site.theme]`, Partlet uses Classic in auto
mode. Discover the bundled choices with:

```bash
partlet theme list
partlet theme check --repo /path/to/source
```

Commit the manifest and push through your normal publishing workflow.
Theme-only changes rebuild pages even when project history is unchanged;
they do not require new history approval. An invalid theme stops the
operation before publication instead of silently falling back.

If you already run a public site, update its Worker to the matching
Partlet version **before publishing themed pages**: older Workers do not
serve the new theme resource URLs. Installing or selecting a theme does
not deploy your Worker. Follow the existing
[upgrade procedure](INSTALLATION.md#upgrades).

## Install a third-party theme

A theme is a directory of CSS and optional declared images. Review its
contents, license and origin before copying it into your source
repository. The [Copper example](../examples/themes/copper/theme.toml)
is a complete starting distribution. From a Partlet source checkout,
copy it into your own source repository:

```bash
SOURCE_REPO=/absolute/path/to/my-monorepo
mkdir -p "$SOURCE_REPO/themes"
cp -R examples/themes/copper "$SOURCE_REPO/themes/copper"
```

Select its directory instead of a bundled name:

```toml
[site.theme]
path = "themes/copper"
mode = "auto"
```

Use `name` or `path`, never both. A theme path is relative to the
manifest's directory and must stay inside the source repository. Use
forward slashes; absolute paths, traversal and symlinks are refused.

Commit the theme directory and manifest on `site.branch`, then validate:

```bash
partlet theme check --repo "$SOURCE_REPO"
```

Validation and local builds read the theme files from the committed
publishing branch, not your uncommitted CSS edits. Commit theme edits
before previewing them. Production publication additionally refuses
relevant checkout files that differ from that committed snapshot. No
theme packages, source-repository Python modules or build hooks execute.
No runtime theme download occurs. An updated theme takes effect when you
commit its contents and publish again.

For a local preview, follow the
[site preview instructions](../worker/README.md#preview-your-site).
Inspect both color modes, a narrow screen, README links, source line
numbers and keyboard focus before using a third-party theme publicly.

Only the stylesheet and explicitly declared images become public.
**These files are additional public content outside project exports.**
Exported-history secret scanning does not establish that theme assets
are safe to publish; inspect the files themselves. Theme CSS is trusted
presentation code: it can hide content or load external images under the
site's existing image policy. The restrictions on script execution are
preserved, but they do not make arbitrary CSS harmless.

Keep the distribution's license and record its source and immutable
revision alongside it. Installation requires no registry, marketplace,
subscription or automatic cloud provisioning.

## Write a theme

Use this distribution layout:

```text
my-theme/
  theme.toml
  style.css
  LICENSE
  assets/       # optional declared raster images
```

The root metadata table uses theme format version 1:

```toml
id = "my-theme"
name = "My theme"
version = "1.0.0"
format_version = 1
modes = ["auto", "light", "dark"]
license = "MIT"
assets = ["assets/pattern.png"]
```

Supply all three modes. `version` identifies your distribution release;
`format_version` identifies the Partlet compatibility contract. Unknown
formats and invalid metadata fail validation. Keep `LICENSE` locally; it
and `theme.toml` are not served as theme resources.

Only `style.css` and the listed assets are published. Assets must be
PNG, JPEG (`.jpg` or `.jpeg`), GIF or WebP with lowercase extensions.
Path segments begin with an ASCII letter, digit, underscore or hyphen
and otherwise contain only those characters and dots. Nested directories
inside `assets/` are allowed; empty segments and dot segments are not.
SVG, HTML, JavaScript and custom fonts are outside format version 1.
Reference declared images relative to `style.css`, for example
`url("assets/pattern.png")`; the published directory layout preserves
that relationship.

Format 1 refuses `@import`, `@font-face`, CSS backslash escapes and
undeclared local image references. Use `url()` for image references;
alternative image functions (`image-set()`, `-webkit-image-set()`,
`image()` and `src()`) are unsupported. Use literal Unicode text when
needed. Explicit HTTPS image URLs remain possible under the existing
image CSP; review them along with the rest of the stylesheet.

Partlet owns the HTML and escapes repository content. Themes use CSS;
they do not replace templates or provide executable plugins. The root
element exposes `data-theme` (the theme ID) and `data-mode` (`auto`,
`light`, or `dark`). Start with light defaults and cover explicit dark
mode and automatic dark preference:

```css
:root { --bg: #fffaf5; --fg: #30251f; }
:root[data-mode="dark"] { --bg: #211b17; --fg: #f7ebdf; }
@media (prefers-color-scheme: dark) {
  :root[data-mode="auto"] { --bg: #211b17; --fg: #f7ebdf; }
}
```

The complete [Copper stylesheet](../examples/themes/copper/style.css)
also overrides link, muted, code-background and focus colors. Set those
coherently; changing the page background alone can make text unreadable.

The stable format-1 tokens are:

| Purpose | Variables |
| -- | -- |
| Main colors | `--fg`, `--muted`, `--bg`, `--line`, `--link`, `--code-bg`, `--focus` |
| Fonts | `--body-font`, `--prose-font`, `--mono-font`, `--font-size`, `--line-height` |
| Layout | `--content-width`, `--space`, `--radius` |
| Code colors | `--syntax-comment`, `--syntax-keyword`, `--syntax-string`, `--syntax-number`, `--syntax-name`, `--syntax-error` |

Use system font stacks. Theme CSS follows Partlet's structural and code
styles so matching selectors override their defaults. Stable styling
hooks include `header.top`, `main`, `.crumbs`, `table.listing`,
`article.readme`, `.hl` and `.hl .linenos`. Preserve readable content,
visible keyboard focus, horizontal scrolling for code and usable narrow
screens. Check text and code colors against their actual backgrounds in
both light and dark modes. Breaking changes to these hooks require a new
theme format version.

## Publication and retained resources

Partlet fingerprints theme inputs and options and serves the resulting
CSS and images at immutable URLs. Resources upload before pages
reference them. Theme changes leave old resources available so cached
pages and projects skipped or failed during a later publication retain
their appearance. Old theme resources accumulate in storage; this
version does not automatically collect them. Reusing the same inputs
reuses the same resource namespace.

The legacy stylesheet remains available for earlier pages.
Worker-generated 404 pages keep Classic styling. Removing a project
rebuilds the index using the stored site presentation; it does not
require the theme's local source directory or change the surviving
site's theme.
