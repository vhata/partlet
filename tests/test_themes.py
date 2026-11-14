import base64
import dataclasses

import pytest
from helpers import Repo

from partlet.gitutil import git
from partlet.manifest import ThemeConfig
from partlet.site import themes
from partlet.site.themes import BUILTIN_THEMES, ThemeError, resolve_theme

METADATA = """id = "ocean"
name = "Ocean"
version = "1.0.0"
format_version = 2
modes = ["auto", "light", "dark"]
license = "MIT"
assets = []
"""
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZV2kAAAAASUVORK5CYII="
)
CONFIG = ThemeConfig(name=None, path="themes/ocean")


def pack(tmp_path, *, metadata=METADATA, css=":root { --link: #14617d; }", files=None):
    repo = Repo(tmp_path / "mono")
    repo.write("themes/ocean/theme.toml", metadata)
    repo.write("themes/ocean/style.css", css)
    repo.write("themes/ocean/LICENSE", "MIT example license")
    for path, data in (files or {}).items():
        repo.write(f"themes/ocean/{path}", data)
    repo.commit("Add reviewed theme")
    return repo


def test_bundled_themes_are_distinct_reproducible_immutable_snapshots():
    digests = set()
    for name in BUILTIN_THEMES:
        resolved = resolve_theme(ThemeConfig(name=name))
        assert resolved == resolve_theme(ThemeConfig(name=name))
        assert resolved.name == name and resolved.mode == "auto"
        assert len(resolved.digest) == 64
        assert (
            resolved.stylesheet_url == f"/_partlet/themes/{resolved.digest}/style.css"
        )
        assert [(r.path, r.content_type) for r in resolved.resources] == [
            ("style.css", "text/css; charset=utf-8")
        ]
        css = resolved.resources[0].data
        assert b"prefers-color-scheme: dark" in css
        assert b'[data-mode="auto"]' in css and b'[data-mode="dark"]' in css
        assert b"--syntax-string:" in css and b"var(--syntax-string)" in css
        assert b":focus-visible" in css and b"max-width: 480px" in css
        with pytest.raises(dataclasses.FrozenInstanceError):
            resolved.name = "changed"
        digests.add(resolved.digest)
    assert len(digests) == len(BUILTIN_THEMES)


def test_mode_is_part_of_theme_identity():
    resolved = [
        resolve_theme(ThemeConfig(name="paper", mode=mode))
        for mode in ("auto", "light", "dark")
    ]
    assert len({theme.digest for theme in resolved}) == 3
    assert len({theme.resources for theme in resolved}) == 1


def test_vendored_theme_publishes_only_allowlisted_content(tmp_path):
    metadata = METADATA.replace("assets = []", 'assets = ["assets/nested/logo.png"]')
    repo = pack(
        tmp_path,
        metadata=metadata,
        css='header.top { background-image: url("assets/nested/logo.png"); }',
        files={
            "assets/nested/logo.png": PNG,
            "private.txt": "private content",
            "assets/not-listed.png": PNG,
        },
    )
    theme = resolve_theme(CONFIG, repo.path)
    assert theme.name == "ocean"
    assert [r.path for r in theme.resources] == ["style.css", "assets/nested/logo.png"]
    assert theme.resources[1].data == PNG
    assert theme.resources[1].content_type == "image/png"
    assert all(b"private content" not in r.data for r in theme.resources)
    assert b'url("assets/nested/logo.png")' in theme.resources[0].data


def test_uses_committed_bytes_and_checks_clean_production_inputs(tmp_path):
    repo = pack(tmp_path)
    before = resolve_theme(CONFIG, repo.path)
    repo.write("themes/ocean/style.css", ":root { --link: red; }")
    assert resolve_theme(CONFIG, repo.path) == before
    with pytest.raises(ThemeError, match="differs from its publishing commit"):
        resolve_theme(CONFIG, repo.path, require_clean=True)
    repo.commit("Change theme only")
    after = resolve_theme(CONFIG, repo.path, require_clean=True)
    assert before.digest != after.digest
    assert b"--link: red" in after.resources[0].data


def test_resolution_keeps_one_revision_when_source_branch_moves(tmp_path, monkeypatch):
    repo = pack(tmp_path)
    original = resolve_theme(CONFIG, repo.path)
    original_git = themes.git
    switched = False

    def moving_git(*args, **kwargs):
        nonlocal switched
        result = original_git(*args, **kwargs)
        if args[:2] == ("cat-file", "blob") and not switched:
            switched = True
            repo.write("themes/ocean/style.css", ":root { --link: #abc; }")
            repo.commit("Move branch during resolution")
        return result

    monkeypatch.setattr(themes, "git", moving_git)
    assert resolve_theme(CONFIG, repo.path) == original
    assert switched
    assert resolve_theme(CONFIG, repo.path).digest != original.digest


def test_custom_theme_is_relative_to_manifest_directory(tmp_path):
    repo = Repo(tmp_path / "mono")
    repo.write("config/partlet.toml", "# source manifest")
    repo.write("config/themes/ocean/theme.toml", METADATA)
    repo.write("config/themes/ocean/style.css", ":root { --space: 30px; }")
    repo.commit("Add nested configuration")
    resolved = resolve_theme(
        CONFIG, repo.path, manifest_path=repo.path / "config/partlet.toml"
    )
    assert b"--space: 30px" in resolved.resources[0].data
    with pytest.raises(ThemeError, match="inside the source repository"):
        resolve_theme(
            CONFIG, repo.path, manifest_path=tmp_path / "outside/partlet.toml"
        )


@pytest.mark.parametrize(
    "path",
    ["", "/etc", "../private", "a/../private", "a/./b", "a//b", "a/", "a\\b", "C:/x"],
)
def test_direct_api_rejects_unsafe_theme_paths(tmp_path, path):
    repo = pack(tmp_path)
    with pytest.raises(ThemeError, match="relative directory"):
        resolve_theme(ThemeConfig(name=None, path=path), repo.path)


@pytest.mark.parametrize("path", ["theme.toml", "style.css", "assets/logo.png"])
def test_rejects_committed_symlink_files(tmp_path, path):
    metadata = METADATA.replace("assets = []", 'assets = ["assets/logo.png"]')
    repo = pack(tmp_path, metadata=metadata, files={"assets/logo.png": PNG})
    target = repo.path / f"themes/ocean/{path}"
    target.unlink()
    repo.write("private.txt", "private file")
    repo.symlink(f"themes/ocean/{path}", "../../private.txt")
    repo.commit("Replace theme file with link")
    with pytest.raises(ThemeError, match="committed regular file"):
        resolve_theme(CONFIG, repo.path)


def test_rejects_committed_symlink_directory(tmp_path):
    repo = pack(tmp_path)
    repo.symlink("themes/linked", "ocean")
    repo.commit("Link theme directory")
    with pytest.raises(ThemeError, match="symlinks are unsupported"):
        resolve_theme(ThemeConfig(name=None, path="themes/linked"), repo.path)


def test_clean_check_rejects_local_symlink_without_reading_target(tmp_path):
    repo = pack(tmp_path)
    expected = resolve_theme(CONFIG, repo.path)
    (repo.path / "themes/ocean/style.css").unlink()
    (repo.path / "themes/ocean/style.css").symlink_to(
        tmp_path / "nonexistent-private-file"
    )
    assert resolve_theme(CONFIG, repo.path) == expected
    with pytest.raises(ThemeError, match="regular-file snapshot"):
        resolve_theme(CONFIG, repo.path, require_clean=True)


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("format_version = 2", "format_version = 1", "format_version"),
        ("format_version = 2", "format_version = true", "format_version"),
        ('id = "ocean"', 'id = "Bad name"', "lowercase stable identifier"),
        ('name = "Ocean"', 'name = ""', "non-empty string"),
        ('version = "1.0.0"', "version = 1", "non-empty string"),
        ('license = "MIT"', "", "missing license"),
        (
            'modes = ["auto", "light", "dark"]',
            'modes = ["light", "dark"]',
            "modes must list",
        ),
        ("assets = []", 'assets = "images"', "assets must be a list"),
        ("assets = []", "assets = [1]", "relative path strings"),
        (
            "assets = []",
            'assets = ["assets/logo.png", "assets/logo.png"]',
            "duplicate assets",
        ),
        ("assets = []", 'assets = ["../private.png"]', "invalid theme asset path"),
        (
            "assets = []",
            'assets = ["assets/../private.png"]',
            "invalid theme asset path",
        ),
        ("assets = []", 'assets = ["assets/icon.svg"]', "unsupported theme asset"),
        ("assets = []", 'assets = ["assets/font.woff2"]', "unsupported theme asset"),
        ("assets = []", 'assets = ["assets/logo.PNG"]', "unsupported theme asset"),
        (
            "assets = []",
            'assets = ["assets/logo.png"]\nprivate = "secret"',
            "unknown private",
        ),
    ],
)
def test_invalid_pack_metadata_fails_before_reading_assets(tmp_path, old, new, message):
    repo = pack(tmp_path, metadata=METADATA.replace(old, new))
    with pytest.raises(ThemeError, match=message):
        resolve_theme(CONFIG, repo.path)


@pytest.mark.parametrize(
    "css, message",
    [
        ('body { background: url("assets/missing.png"); }', "undeclared asset"),
        ('body { background: url("../../private.png"); }', "undeclared asset"),
        ('body { background: url("/private.png"); }', "undeclared asset"),
        ('body { background: url("assets/%6cogo.png"); }', "undeclared asset"),
        ('body { background: url("data:image/png;base64,a"); }', "undeclared asset"),
        ('@import "other.css";', "imports or custom fonts"),
        (
            '@font-face { font-family: custom; src: url("font.woff2"); }',
            "imports or custom fonts",
        ),
        ('body { background: u/**/rl("private.png"); }', "undeclared asset"),
        ('body { content: "\\2600"; }', "CSS escapes"),
        ("body { background: url( nested(foo) ); }", "unsupported url"),
        ('body { background: image-set("secret.png" 1x); }', "requires url"),
        ('body { background: -webkit-image-set("secret.png" 1x); }', "requires url"),
        ('body { background: image("secret.png", red); }', "requires url"),
        ('body { background: src("secret.png"); }', "requires url"),
        (b"body { content: '\xff'; }", "must be UTF-8"),
    ],
)
def test_invalid_css_fails_clearly(tmp_path, css, message):
    repo = pack(tmp_path, css=css)
    with pytest.raises(ThemeError, match=message):
        resolve_theme(CONFIG, repo.path)


def test_https_image_urls_remain_trusted_publisher_content(tmp_path):
    repo = pack(
        tmp_path,
        css='header.top { background: url("https://example.invalid/image.png"); }',
    )
    assert (
        b"https://example.invalid/image.png"
        in resolve_theme(CONFIG, repo.path).resources[0].data
    )


def test_comment_tokens_inside_quoted_url_remain_literal(tmp_path):
    repo = pack(
        tmp_path,
        metadata=METADATA.replace("assets = []", 'assets = ["assets/ab.png"]'),
        css='body { background: url("assets/a/*x*/b.png"); }',
        files={"assets/ab.png": PNG},
    )
    with pytest.raises(ThemeError, match="undeclared asset"):
        resolve_theme(CONFIG, repo.path)


def test_css_comments_do_not_create_spurious_asset_references(tmp_path):
    repo = pack(
        tmp_path,
        css='/* background: url("private.png") */ body { content: "/* literal comment */"; }',
    )
    assert resolve_theme(CONFIG, repo.path).name == "ocean"


def test_unsupported_raster_bytes_rejected(tmp_path):
    repo = pack(
        tmp_path,
        metadata=METADATA.replace("assets = []", 'assets = ["assets/logo.png"]'),
        files={"assets/logo.png": "<svg>active markup</svg>"},
    )
    with pytest.raises(ThemeError, match="declared raster format"):
        resolve_theme(CONFIG, repo.path)


@pytest.mark.parametrize("filename", ["png", "jpg", "jpeg", "gif", "webp"])
def test_extensionless_asset_names_are_rejected(tmp_path, filename):
    repo = pack(
        tmp_path,
        metadata=METADATA.replace("assets = []", f'assets = ["assets/{filename}"]'),
    )
    with pytest.raises(ThemeError, match="filename extension is required"):
        resolve_theme(CONFIG, repo.path)


def test_asset_bytes_and_metadata_are_part_of_theme_identity(tmp_path):
    repo = pack(
        tmp_path,
        metadata=METADATA.replace("assets = []", 'assets = ["assets/logo.png"]'),
        files={"assets/logo.png": PNG},
    )
    before = resolve_theme(CONFIG, repo.path)
    repo.write("themes/ocean/assets/logo.png", PNG + b"extra image metadata")
    repo.commit("Change declared image")
    changed_asset = resolve_theme(CONFIG, repo.path)
    assert changed_asset.digest != before.digest
    repo.write(
        "themes/ocean/theme.toml",
        METADATA.replace("assets = []", 'assets = ["assets/logo.png"]').replace(
            'version = "1.0.0"', 'version = "1.0.1"'
        ),
    )
    repo.commit("Update theme release metadata")
    assert resolve_theme(CONFIG, repo.path).digest != changed_asset.digest


def test_only_configured_branch_inputs_are_used(tmp_path):
    repo = pack(tmp_path)
    theme = resolve_theme(CONFIG, repo.path)
    git("checkout", "-q", "-b", "other", cwd=repo.path)
    repo.write("themes/ocean/style.css", ":root { --space: 99px; }")
    repo.commit("Work on other branch")
    assert resolve_theme(CONFIG, repo.path) == theme
    assert resolve_theme(CONFIG, repo.path, branch="other").digest != theme.digest


def test_uncommitted_theme_is_not_publishable(tmp_path):
    repo = pack(tmp_path)
    repo.write("themes/untracked/theme.toml", METADATA)
    repo.write("themes/untracked/style.css", "body {}")
    with pytest.raises(ThemeError, match="not a committed directory"):
        resolve_theme(ThemeConfig(name=None, path="themes/untracked"), repo.path)
