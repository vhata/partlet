"""Decide whether a new export may replace what is already published."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from partlet.gitutil import GitError, git


class HistoryError(Exception):
    """The new export must not be published."""


@dataclass(frozen=True)
class Decision:
    action: Literal["publish", "unchanged", "rewrite"]
    reason: str


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        git("cat-file", "-e", f"{ancestor}^{{commit}}", cwd=repo)
        git("merge-base", "--is-ancestor", ancestor, descendant, cwd=repo)
    except GitError:
        return False
    return True


def check_history(
    repo: Path,
    new_tip: str,
    published_tip: str | None,
    approved: str | None,
    allow_rewrite_of: str | None,
) -> Decision:
    if approved is None:
        raise HistoryError("project is not approved; run partlet review")
    if published_tip == new_tip:
        return Decision("unchanged", "already published")
    if published_tip is not None and is_ancestor(repo, published_tip, new_tip):
        return Decision("publish", f"fast-forward from {published_tip[:12]}")
    if published_tip is not None and allow_rewrite_of != published_tip:
        raise HistoryError(
            f"history rewrite: published tip {published_tip[:12]} is not an ancestor of "
            f"{new_tip[:12]}; run partlet review --allow-rewrite if this is intended"
        )
    if not is_ancestor(repo, approved, new_tip):
        raise HistoryError(
            f"approved commit {approved[:12]} is not in the history of {new_tip[:12]}; "
            "re-run partlet review"
        )
    if published_tip is None:
        return Decision("publish", "first publication")
    return Decision("rewrite", f"rewrite of {published_tip[:12]} allowed by manifest")
