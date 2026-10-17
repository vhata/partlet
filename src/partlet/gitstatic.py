"""Lay out a published repository for Git's dumb HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import git_out
from partlet.store import Store

MAX_PACKS = 20
PACK_EXTS = ("pack", "idx")


@dataclass(frozen=True)
class GitState:
    tip: str | None
    packs: tuple[str, ...]


@dataclass(frozen=True)
class PackPlan:
    tip: str
    packs: tuple[str, ...]


def read_state(store: Store, git_prefix: str) -> GitState:
    tip = None
    refs = store.get(f"{git_prefix}/info/refs")
    for line in (refs or b"").decode("utf-8").splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main":
            tip = sha
    raw_packs = store.get(f"{git_prefix}/objects/info/packs")
    packs = tuple(
        line[2:].removesuffix(".pack")
        for line in (raw_packs or b"").decode("utf-8").splitlines()
        if line.startswith("P ")
    )
    return GitState(tip, packs)


def upload_pack(
    store: Store,
    git_prefix: str,
    repo: Path,
    new_tip: str,
    old: GitState,
    workdir: Path,
    full: bool = False,
) -> PackPlan:
    """Upload one pack covering what `old` lacks; return the resulting pack list."""
    consolidate = full or old.tip is None or len(old.packs) >= MAX_PACKS
    workdir.mkdir(parents=True, exist_ok=True)
    revs = f"{new_tip}\n" + ("" if consolidate else f"^{old.tip}\n")
    digest = git_out(
        "pack-objects",
        "--revs",
        "--delta-base-offset",
        "-q",
        str(workdir / "pack"),
        cwd=repo,
        input=revs.encode(),
    )
    pack = f"pack-{digest}"
    for ext in PACK_EXTS:
        store.put(
            f"{git_prefix}/objects/pack/{pack}.{ext}",
            (workdir / f"{pack}.{ext}").read_bytes(),
        )
    return PackPlan(new_tip, (pack,) if consolidate else (*old.packs, pack))


def _put_pack_list(store: Store, git_prefix: str, packs: tuple[str, ...]) -> None:
    info_packs = "".join(f"P {p}.pack\n" for p in packs) + "\n"
    store.put(f"{git_prefix}/objects/info/packs", info_packs.encode())


def write_pointers(
    store: Store, git_prefix: str, plan: PackPlan, old: GitState
) -> None:
    """Move the pack list and refs to `plan`, never leaving refs short of a pack.

    A plan that drops packs lists the old and new packs together until
    `info/refs` has moved, then writes its own list.
    """
    dropped = tuple(p for p in old.packs if p not in plan.packs)
    _put_pack_list(store, git_prefix, (*dropped, *plan.packs))
    store.put(f"{git_prefix}/info/refs", f"{plan.tip}\trefs/heads/main\n".encode())
    store.put(f"{git_prefix}/HEAD", b"ref: refs/heads/main\n")
    if dropped:
        _put_pack_list(store, git_prefix, plan.packs)
