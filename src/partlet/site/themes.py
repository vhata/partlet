"""Resolve reproducible, non-executable site themes before publishing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from partlet.gitutil import GitError, git, git_out
from partlet.manifest import NAME_RE, THEME_MODES, ThemeConfig

BUILTIN_THEMES = {
    "classic": "Clean repository panels and a quiet teal accent (default)",
    "paper": "Spacious serif prose and a warm reading surface",
    "terminal": "Restrained monospace layout with code emphasis",
}
FORMAT_VERSION = 1
_SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
_ASSET_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
_URL = re.compile(
    r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s()'\"]+))\s*\)", re.IGNORECASE
)


class ThemeError(Exception):
    """A configured theme is missing, incompatible or unsafe to publish."""


@dataclass(frozen=True)
class ThemePresentation:
    name: str
    mode: str
    digest: str

    @property
    def stylesheet_url(self) -> str:
        return f"/_partlet/themes/{self.digest}/style.css"


@dataclass(frozen=True)
class ThemeResource:
    path: str
    data: bytes
    content_type: str


@dataclass(frozen=True)
class ResolvedTheme(ThemePresentation):
    resources: tuple[ThemeResource, ...]


def _relative_directory(value: str) -> tuple[str, ...]:
    parts = value.split("/")
    if (
        not value
        or any(part in ("", ".", "..") for part in parts)
        or any(char in value for char in "\\:\0")
    ):
        raise ThemeError("theme path must be a relative directory without traversal")
    return tuple(parts)


def _asset_type(path: object) -> str:
    if not isinstance(path, str):
        raise ThemeError("theme assets must be relative path strings inside assets/")
    parts = path.split("/")
    if (
        len(parts) < 2
        or parts[0] != "assets"
        or any(not _SEGMENT.fullmatch(part) for part in parts)
    ):
        raise ThemeError(f"invalid theme asset path {path!r}; use assets/<raster file>")
    if "." not in parts[-1]:
        raise ThemeError(
            f"unsupported theme asset {path!r}; a raster filename extension is required"
        )
    extension = parts[-1].rsplit(".", 1)[-1]
    if extension not in _ASSET_TYPES:
        raise ThemeError(
            f"unsupported theme asset {path!r}; use PNG, JPEG, GIF or WebP"
        )
    return _ASSET_TYPES[extension]


def _raster(path: str, data: bytes, content_type: str) -> None:
    valid = {
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not valid[content_type]:
        raise ThemeError(
            f"theme asset {path!r} does not have its declared raster format"
        )


def _metadata(data: bytes) -> dict:
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ThemeError(f"invalid theme.toml: {exc}") from exc
    required = {"id", "name", "version", "format_version", "modes", "license", "assets"}
    missing, unknown = required - raw.keys(), raw.keys() - required
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown {', '.join(sorted(unknown))}")
        raise ThemeError(f"theme.toml: {'; '.join(details)}")
    if (
        type(raw["format_version"]) is not int
        or raw["format_version"] != FORMAT_VERSION
    ):
        raise ThemeError("unsupported theme format_version; this Partlet supports 1")
    for key in ("id", "name", "version", "license"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ThemeError(f"theme.toml {key} must be a non-empty string")
    if not NAME_RE.fullmatch(raw["id"]):
        raise ThemeError("theme.toml id must be a lowercase stable identifier")
    modes = raw["modes"]
    if (
        not isinstance(modes, list)
        or len(modes) != len(THEME_MODES)
        or any(not isinstance(mode, str) for mode in modes)
        or set(modes) != set(THEME_MODES)
    ):
        raise ThemeError("theme.toml modes must list auto, light and dark exactly once")
    assets = raw["assets"]
    if not isinstance(assets, list):
        raise ThemeError("theme.toml assets must be a list of relative raster paths")
    for path in assets:
        _asset_type(path)
    if len(set(assets)) != len(assets):
        raise ThemeError("theme.toml contains duplicate assets")
    return raw


def _without_css_comments(css: str) -> str:
    """Remove comments outside strings; quoted URL contents stay literal."""
    output = []
    quote = None
    i = 0
    while i < len(css):
        char = css[i]
        if quote is not None:
            output.append(char)
            if char == quote:
                quote = None
            i += 1
        elif char in ("'", '"'):
            quote = char
            output.append(char)
            i += 1
        elif css.startswith("/*", i):
            end = css.find("*/", i + 2)
            if end == -1:
                raise ThemeError("theme style.css contains an unterminated comment")
            i = end + 2
        else:
            output.append(char)
            i += 1
    return "".join(output)


def _check_css(data: bytes, assets: set[str]) -> None:
    try:
        css = data.decode("utf-8")
    except UnicodeError as exc:
        raise ThemeError("theme style.css must be UTF-8") from exc
    # A deliberately small, readable pack format, not a CSS security sandbox.
    # Escaped identifiers/URLs and imports would make the asset inventory
    # ambiguous without a full CSS parser. Use literal characters in v1.
    if "\\" in css:
        raise ThemeError(
            "theme CSS escapes are unsupported in format 1; use literal characters"
        )
    css = _without_css_comments(css)
    if re.search(r"@(?:import|font-face)\b", css, re.IGNORECASE):
        raise ThemeError("theme format 1 does not support CSS imports or custom fonts")
    if re.search(
        r"(?:\bimage(?:-set)?|-webkit-image-set|\bsrc)\s*\(", css, re.IGNORECASE
    ):
        raise ThemeError(
            "theme format 1 requires url() image references; image(), image-set() and src() are unsupported"
        )
    for match in _URL.finditer(css):
        value = next(group for group in match.groups() if group is not None)
        # Existing PAGE_CSP permits HTTPS image requests. These remain
        # publisher-trusted, and are not copied into or fetched by the build.
        if value.startswith("https://"):
            continue
        if value not in assets:
            raise ThemeError(f"theme CSS references undeclared asset {value!r}")
    if re.search(r"url\s*\(", _URL.sub("", css), re.IGNORECASE):
        raise ThemeError("theme CSS contains an unsupported url() expression")


class _CommittedFiles:
    """Read only declared regular blobs from one frozen source revision."""

    def __init__(
        self,
        repo: Path,
        branch: str,
        manifest_path: Path | None,
        path: str,
        require_clean: bool,
    ) -> None:
        self.root = Path(git_out("rev-parse", "--show-toplevel", cwd=repo)).resolve()
        self.revision = git_out(
            "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=self.root
        )
        manifest = manifest_path or self.root / "partlet.toml"
        manifest = Path(os.path.abspath(manifest))
        try:
            parent = manifest.parent.relative_to(self.root)
        except ValueError:
            raise ThemeError(
                "theme manifest must be inside the source repository"
            ) from None
        self.base = (*parent.parts, *_relative_directory(path))
        self.require_clean = require_clean
        # Inspect ancestors explicitly: Git does not descend through a
        # symlink, and a missing blob alone would hide the actual problem.
        for i in range(1, len(self.base) + 1):
            relative = "/".join(self.base[:i])
            record = self._entry(relative)
            if record is None or record[0] != "040000":
                raise ThemeError(
                    f"theme directory {relative!r} is not a committed directory (symlinks are unsupported)"
                )

    def _entry(self, relative: str) -> tuple[str, str] | None:
        entries = git(
            "ls-tree", "-z", self.revision, "--", relative, cwd=self.root
        ).stdout.split(b"\0")
        for entry in entries:
            if not entry:
                continue
            info, name = entry.split(b"\t", 1)
            if name.decode("utf-8") == relative:
                mode, _kind, oid = info.decode("ascii").split()
                return mode, oid
        return None

    def read(self, path: str) -> bytes:
        relative = "/".join((*self.base, *path.split("/")))
        # The pack contract chooses path names; still check every directory
        # so a declared nested asset cannot traverse a committed symlink.
        for parent in Path(relative).parents:
            if str(parent) == ".":
                continue
            entry = self._entry(parent.as_posix())
            if entry is None or entry[0] != "040000":
                raise ThemeError(
                    f"theme path {parent.as_posix()!r} is not a committed directory"
                )
        entry = self._entry(relative)
        if entry is None or entry[0] not in ("100644", "100755"):
            raise ThemeError(
                f"theme file {relative!r} must be a committed regular file; symlinks are unsupported"
            )
        data = git("cat-file", "blob", entry[1], cwd=self.root).stdout
        if self.require_clean:
            self._check_clean(relative, data)
        return data

    def _check_clean(self, relative: str, data: bytes) -> None:
        parts = relative.split("/")
        for i in range(1, len(parts) + 1):
            target = self.root.joinpath(*parts[:i])
            mode = target.lstat().st_mode
            expected = stat.S_ISREG(mode) if i == len(parts) else stat.S_ISDIR(mode)
            if not expected:
                raise ThemeError(
                    f"theme path {relative!r} differs from the committed regular-file snapshot"
                )
        if self.root.joinpath(*parts).read_bytes() != data:
            raise ThemeError(
                f"theme file {relative!r} differs from its publishing commit; commit it first"
            )


def _bundle(name: str) -> bytes:
    return resources.files("partlet.site").joinpath("themes", name).read_bytes()


def resolve_theme(
    config: ThemeConfig | None = None,
    repo: Path | None = None,
    *,
    branch: str = "main",
    manifest_path: Path | None = None,
    require_clean: bool = False,
) -> ResolvedTheme:
    """Snapshot a bundled theme or declared blobs from the publishing commit.

    Local previews use committed custom-theme bytes, even with local edits.
    Production callers additionally require checkout bytes to match. This
    function does no writes, dependency installation or network requests.
    """
    config = config or ThemeConfig()
    if config.mode not in THEME_MODES:
        raise ThemeError(f"theme mode must be one of {', '.join(THEME_MODES)}")
    try:
        metadata: dict = {"format_version": FORMAT_VERSION}
        assets: list[ThemeResource] = []
        if config.path is not None:
            if config.name is not None:
                raise ThemeError("theme name and path are mutually exclusive")
            if repo is None:
                raise ThemeError("a source repository is required for a vendored theme")
            committed = _CommittedFiles(
                repo, branch, manifest_path, config.path, require_clean
            )
            metadata = _metadata(committed.read("theme.toml"))
            name = metadata["id"]
            css = committed.read("style.css")
            _check_css(css, set(metadata["assets"]))
            for path in sorted(metadata["assets"]):
                content_type = _asset_type(path)
                data = committed.read(path)
                _raster(path, data, content_type)
                assets.append(ThemeResource(path, data, content_type))
        else:
            name = config.name
            if name not in BUILTIN_THEMES:
                raise ThemeError(
                    f"unknown bundled theme {name!r}; run partlet theme list"
                )
            css = _bundle(f"{name}.css")
        combined = b"\n".join((_bundle("base.css"), _bundle("syntax.css"), css)) + b"\n"
        output = (
            ThemeResource("style.css", combined, "text/css; charset=utf-8"),
            *assets,
        )
        digest = hashlib.sha256()
        digest.update(
            json.dumps(
                {"metadata": metadata, "name": name, "mode": config.mode},
                sort_keys=True,
            ).encode()
        )
        for resource in output:
            # Length framing prevents ambiguous concatenations of paths/data.
            for value in (
                resource.path.encode(),
                resource.content_type.encode(),
                resource.data,
            ):
                digest.update(len(value).to_bytes(8, "big"))
                digest.update(value)
        return ResolvedTheme(name, config.mode, digest.hexdigest(), output)
    except (GitError, OSError, UnicodeError) as exc:
        raise ThemeError(f"cannot resolve theme: {exc}") from exc
