"""Rewrite relative links in rendered Markdown to project URLs."""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit

from partlet.site import urls


class Linker:
    def __init__(self, project: str, files: set[str], dirs: set[str]):
        self.project = project
        self.files = files
        self.dirs = dirs

    def resolve(self, base_dir: str, href: str, raw: bool = False) -> str:
        if not href or href.startswith(("/", "#")):
            return href
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return href
        target = posixpath.normpath(posixpath.join(base_dir, unquote(parts.path)))
        if target == ".":
            target = ""
        if target == ".." or target.startswith("../"):
            return href
        if raw:
            url = urls.raw_url(self.project, target)
        elif target in self.dirs:
            url = urls.tree_url(self.project, target)
        else:
            url = urls.blob_url(self.project, target)
        if parts.query:
            url += f"?{parts.query}"
        if parts.fragment:
            url += f"#{parts.fragment}"
        return url
