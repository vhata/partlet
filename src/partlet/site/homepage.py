"""Explicit public homepage inputs, read from one committed snapshot."""

from __future__ import annotations

import json
import stat
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from markupsafe import Markup

from partlet.gitutil import git, git_out
from partlet.manifest import Site
from partlet.site.markdown import render_markdown
from partlet.site.models import SiteIdentity
from partlet.store import StoreError


class HomepageError(ValueError):
    pass


class HomepageLinks:
    def resolve(self, base_dir: str, href: str, raw: bool = False) -> str:
        parts = urlsplit(href)
        if (href.startswith(("#", "/")) and not href.startswith("//")) or (
            parts.scheme in ("https", "http", "mailto")
            and (not raw or parts.scheme != "mailto")
        ):
            return href
        raise HomepageError(
            f"site.readme link {href!r} is ambiguous or unsupported; use a public root-relative URL, fragment, or absolute HTTP(S) URL"
        )


def load_homepage(
    repo: Path, site: Site, *, require_clean: bool = False
) -> Markup | None:
    if site.readme is None:
        return None
    path = site.readme
    if (
        not path
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 for c in path)
        or any(p in ("", ".", "..") for p in path.split("/"))
        or not path.lower().endswith((".md", ".markdown"))
    ):
        raise HomepageError(
            "site.readme must be a source-repository-relative Markdown file without traversal"
        )
    root = Path(git_out("rev-parse", "--show-toplevel", cwd=repo))
    revision = git_out(
        "rev-parse", "--verify", f"refs/heads/{site.branch}^{{commit}}", cwd=root
    )
    parts = path.split("/")
    oid = ""
    for i in range(1, len(parts) + 1):
        relative = "/".join(parts[:i])
        records = git("ls-tree", "-z", revision, "--", relative, cwd=root).stdout.split(
            b"\0"
        )
        match = [
            r.split(b"\t", 1)[0].split()
            for r in records
            if r and r.split(b"\t", 1)[1] == relative.encode()
        ]
        modes = (b"100644", b"100755") if i == len(parts) else (b"040000",)
        if len(match) != 1 or match[0][0] not in modes:
            raise HomepageError(
                "site.readme must name a committed regular Markdown file; missing files and symlinks are unsupported"
            )
        oid = match[0][2].decode()
        if require_clean:
            target = root.joinpath(*parts[:i])
            mode = target.lstat().st_mode
            if not (stat.S_ISREG(mode) if i == len(parts) else stat.S_ISDIR(mode)):
                raise HomepageError(
                    "site.readme differs from its committed regular-file snapshot"
                )
    data = git("cat-file", "blob", oid, cwd=root).stdout
    if require_clean and root.joinpath(*parts).read_bytes() != data:
        raise HomepageError(
            "site.readme has uncommitted changes; commit before publishing"
        )
    return Markup(render_markdown(data.decode("utf-8"), "", HomepageLinks()))


class _SafeHTML(HTMLParser):
    """Validate the durable rendered slot before restoring its trust marker."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.output = []

    def handle_data(self, data):
        self.output.append(escape(data, quote=False))

    def handle_starttag(self, tag, attrs):
        if tag not in {
            "p",
            "a",
            "img",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "li",
            "blockquote",
            "pre",
            "code",
            "em",
            "strong",
            "s",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        }:
            raise ValueError("unsafe homepage element")
        for key, value in attrs:
            if key in ("href", "src") and tag in ("a", "img"):
                HomepageLinks().resolve("", value or "", raw=key == "src")
            elif (
                key == "style"
                and tag in ("th", "td")
                and value
                in ("text-align:left", "text-align:right", "text-align:center")
                or key == "class"
                and tag == "code"
                and value
                and value.startswith("language-")
            ):
                continue
            elif key not in (
                {"alt", "title"}
                if tag == "img"
                else {"title"}
                if tag == "a"
                else {"start"}
                if tag == "ol"
                else set()
            ):
                raise ValueError("unsafe homepage attribute")

        attributes = "".join(
            f' {key}="{escape(value or "", quote=True)}"' for key, value in attrs
        )
        self.output.append(f"<{tag}{attributes}>")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, [])
        self.output.pop()
        self.output.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_decl(self, decl):
        raise ValueError("unsafe homepage declaration")


def stored_homepage(
    raw: bytes | None, site: Site
) -> tuple[SiteIdentity, Markup | None]:
    if raw is None:
        return SiteIdentity(site.name, site.tagline), None
    try:
        record = json.loads(raw)
        if not isinstance(record, dict) or set(record) != {
            "version",
            "name",
            "tagline",
            "intro_html",
        }:
            raise ValueError("invalid fields")
        if type(record["version"]) is not int or record["version"] != 1:
            raise ValueError("invalid version")
        if not all(isinstance(record[k], str) for k in ("name", "tagline")):
            raise ValueError("invalid identity")
        record["name"].encode("utf-8")
        record["tagline"].encode("utf-8")
        intro = record["intro_html"]
        if intro is not None:
            if not isinstance(intro, str):
                raise ValueError("invalid intro")
            intro.encode("utf-8")
            parser = _SafeHTML(convert_charrefs=True)
            parser.feed(intro)
            parser.close()
            intro = "".join(parser.output)
        return SiteIdentity(record["name"], record["tagline"]), Markup(
            intro
        ) if intro is not None else None
    except (ValueError, TypeError, UnicodeError) as exc:
        raise StoreError("invalid stored site identity; no index rebuilt") from exc
