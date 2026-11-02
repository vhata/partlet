"""The GitHub Actions step summary: one table row per project."""

from __future__ import annotations

from pathlib import Path

from partlet.publish import ProjectResult

REASON_LIMIT = 300


def _cell(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > REASON_LIMIT:
        text = text[: REASON_LIMIT - 3] + "..."
    for raw, escaped in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|")):
        text = text.replace(raw, escaped)
    return text


def summary_markdown(
    title: str,
    results: list[ProjectResult],
    versions: dict[str, str],
    error: str | None = None,
) -> str:
    lines = [
        f"## {title}",
        "",
        "| Project | Status | Tip | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        tip = f"`{r.tip[:12]}`" if r.tip else ""
        lines.append(f"| {_cell(r.name)} | {r.status} | {tip} | {_cell(r.reason)} |")
    if not results:
        lines.append("| (no projects) | | | |")
    tools = ", ".join(f"{name} {version}" for name, version in versions.items())
    if error is not None:
        lines += ["", f"Failed: {_cell(error)}"]
    lines += ["", f"Tools: {_cell(tools)}", ""]
    return "\n".join(lines)


def write_summary(path: Path | None, text: str) -> None:
    """Append to the step summary file, if there is one."""
    if path is not None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
