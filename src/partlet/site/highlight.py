"""Syntax highlighting for file pages."""

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(
    linenos="table", lineanchors="L", anchorlinenos=True, cssclass="hl"
)


def highlight_file(path: str, text: str) -> str:
    try:
        lexer = get_lexer_for_filename(path, text, stripnl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False)
    return highlight(text, lexer, _FORMATTER)


def pygments_css() -> str:
    return _FORMATTER.get_style_defs(".hl")
