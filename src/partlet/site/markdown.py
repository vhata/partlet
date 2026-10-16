"""Render README Markdown safely."""

from __future__ import annotations

from collections.abc import Iterator

from markdown_it import MarkdownIt
from markdown_it.token import Token

from partlet.site.links import Linker


def _parser() -> MarkdownIt:
    # html=False escapes raw HTML; markdown-it's link validation drops javascript: URLs.
    return MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def _walk(tokens: list[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token
        if token.children:
            yield from _walk(token.children)


def render_markdown(text: str, base_dir: str, linker: Linker) -> str:
    md = _parser()
    tokens = md.parse(text)
    for token in _walk(tokens):
        if token.type == "link_open":
            token.attrSet(
                "href", linker.resolve(base_dir, str(token.attrGet("href") or ""))
            )
        elif token.type == "image":
            token.attrSet(
                "src",
                linker.resolve(base_dir, str(token.attrGet("src") or ""), raw=True),
            )
    return md.renderer.render(tokens, md.options, {})
