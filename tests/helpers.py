"""Helpers for building throwaway git repositories and serving directories."""

from __future__ import annotations

import difflib
import functools
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from partlet.gitutil import git, git_out

EPOCH = 1767225600  # 2026-01-01T00:00:00Z


class Repo:
    """A non-bare repository with deterministic commit timestamps."""

    def __init__(self, path: Path, branch: str = "main"):
        self.path = path
        self._tick = 0
        path.mkdir(parents=True)
        git("init", "-q", "-b", branch, cwd=path)
        git("config", "user.name", "Test Author", cwd=path)
        git("config", "user.email", "author@example.com", cwd=path)
        git("config", "commit.gpgsign", "false", cwd=path)

    def write(self, rel: str, content: str | bytes) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        target.write_bytes(content)

    def symlink(self, rel: str, target: str) -> None:
        link = self.path / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

    def mv(self, src: str, dst: str) -> None:
        (self.path / dst).parent.mkdir(parents=True, exist_ok=True)
        git("mv", src, dst, cwd=self.path)

    def rm(self, rel: str) -> None:
        git("rm", "-r", "-q", rel, cwd=self.path)

    def commit(self, message: str) -> str:
        self._tick += 1
        date = f"{EPOCH + self._tick * 60} +0000"
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        git("add", "-A", cwd=self.path)
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.path, env=env)
        return git_out("rev-parse", "HEAD", cwd=self.path)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def serve_directory(root: Path) -> Iterator[str]:
    """Serve `root` over plain HTTP on a free port; yields the base URL."""
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# --- Tripwire: notice when a test run changes a real repository or git config.
#
# Everything here reads files only. The one git call is `locate_repo`, which
# runs `git rev-parse` with every GIT_* variable removed.

# Refs watched in every repository, besides whatever the HEADs name. Other
# agents legitimately move other branches and rewrite packed-refs, so the
# watched refs are compared by resolved value, never by the files around them.
DEFAULT_WATCHED_REFS = ("refs/heads/main",)


def user_gitconfig_paths(env: Mapping[str, str]) -> list[Path]:
    """The user-level git config files that `env` makes git read."""
    if env.get("GIT_CONFIG_GLOBAL"):
        return [Path(env["GIT_CONFIG_GLOBAL"])]
    home = Path(env.get("HOME") or "~").expanduser()
    xdg = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    return [home / ".gitconfig", xdg / "git" / "config"]


def locate_repo(start: Path) -> tuple[Path, Path]:
    """The (git dir, common dir) of the repository containing `start`.

    Raises LookupError, with the reason, if there is none.
    """
    # Drop every GIT_* variable except the ceiling, which only limits how far
    # discovery climbs and so cannot point git at a different repository.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") or k == "GIT_CEILING_DIRECTORIES"
    }
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            cwd=start,
            env=env,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise LookupError(f"cannot run git: {exc}") from exc
    lines = proc.stdout.splitlines()
    if proc.returncode != 0 or len(lines) < 2:
        raise LookupError(f"git rev-parse failed in {start}: {proc.stderr.strip()}")
    return Path(lines[0]), (start / lines[1]).resolve()


def uses_reftable(common_dir: Path) -> bool:
    try:
        config = (common_dir / "config").read_bytes()
    except OSError:
        return False
    return bool(re.search(rb"(?im)^\s*refstorage\s*=\s*reftable\s*$", config))


def _head_branch(head_file: Path) -> str | None:
    try:
        head = head_file.read_text("utf-8", "replace").strip()
    except OSError:
        return None
    if head.startswith("ref:") and head[4:].strip().startswith("refs/"):
        return head[4:].strip()
    return None


def _packed_refs(common_dir: Path) -> dict[str, bytes]:
    try:
        data = (common_dir / "packed-refs").read_bytes()
    except OSError:
        return {}
    packed: dict[str, bytes] = {}
    for line in data.splitlines():
        if not line or line[:1] in (b"#", b"^"):
            continue
        sha, _, name = line.partition(b" ")
        packed[name.decode("utf-8", "replace")] = sha
    return packed


def watched_refs(
    git_dir: Path, common_dir: Path, extra: Iterable[str] = ()
) -> list[str]:
    """Ref names to watch: each HEAD's branch, the defaults, and `extra`."""
    names = [
        _head_branch(git_dir / "HEAD"),
        _head_branch(common_dir / "HEAD"),
        *DEFAULT_WATCHED_REFS,
        *extra,
    ]
    return list(dict.fromkeys(n for n in names if n))


def state_files(
    git_dir: Path, common_dir: Path, gitconfigs: Sequence[Path] = ()
) -> dict[str, Path]:
    """The plain files whose bytes are watched, by key."""
    files = {
        "config": common_dir / "config",
        "config.worktree": git_dir / "config.worktree",
        "HEAD": git_dir / "HEAD",
    }
    if common_dir != git_dir:
        files["common-HEAD"] = common_dir / "HEAD"
        try:
            gitfile = (git_dir / "gitdir").read_text("utf-8", "replace").strip()
        except OSError:
            gitfile = ""
        if gitfile:
            files["gitfile"] = Path(gitfile)
    for path in gitconfigs:
        files[str(path)] = path
    return files


def snapshot_repo_state(
    git_dir: Path,
    common_dir: Path,
    gitconfigs: Sequence[Path] = (),
    refs: Iterable[str] = (),
) -> dict[str, bytes | None]:
    """Raw bytes (None if missing) of the files a runaway test could rewrite.

    Refs are keyed by name and hold their resolved value: the loose ref file if
    present, else its line in packed-refs. They are skipped, since this reads
    files only, when the repository stores refs as reftable. `refs` adds names
    to watch beyond the defaults, so that a later snapshot covers the refs an
    earlier one resolved.
    """
    state: dict[str, bytes | None] = {}
    for key, path in state_files(git_dir, common_dir, gitconfigs).items():
        try:
            state[key] = path.read_bytes()
        except OSError:
            state[key] = None
    if not uses_reftable(common_dir):
        packed = _packed_refs(common_dir)
        for ref in watched_refs(git_dir, common_dir, refs):
            try:
                state[ref] = (common_dir / ref).read_bytes().strip()
            except OSError:
                state[ref] = packed.get(ref)
    return state


def diff_repo_state(
    before: dict[str, bytes | None], after: dict[str, bytes | None]
) -> list[str]:
    """Keys whose captured bytes differ between two snapshots.

    A key present in only one snapshot is ignored: that is a ref that became
    watched because HEAD moved, and HEAD itself is reported.
    """
    return sorted(k for k in before.keys() & after.keys() if before[k] != after[k])


class TripwireError(Exception):
    """The test run changed a real git file."""


def _text(data: bytes | None) -> list[str]:
    return [] if data is None else data.decode("utf-8", "replace").splitlines()


class RepoTripwire:
    """Backs up a repository's watched git state and checks it afterwards.

    Never raises on construction. If the repository cannot be found, or its
    refs cannot be watched, `notes` says so and the run should show them.
    """

    def __init__(
        self,
        start: Path,
        gitconfigs: Sequence[Path] = (),
        backup_root: Path | None = None,
    ):
        self.notes: list[str] = []
        self.backup_dir: Path | None = None
        self.gitconfigs = list(gitconfigs)
        try:
            self.git_dir, self.common_dir = locate_repo(start)
        except LookupError as exc:
            self.notes.append(f"repository tripwire DISABLED: {exc}")
            return
        if uses_reftable(self.common_dir):
            self.notes.append(
                "repository tripwire: refs are stored as reftable; "
                "refs are NOT watched (config files still are)"
            )
        self.before = snapshot_repo_state(
            self.git_dir, self.common_dir, self.gitconfigs
        )
        self.backup_dir = Path(
            tempfile.mkdtemp(prefix="partlet-tripwire-", dir=backup_root)
        )
        self._write_backup()

    @property
    def active(self) -> bool:
        return self.backup_dir is not None

    def _write_backup(self) -> None:
        assert self.backup_dir is not None
        files = state_files(self.git_dir, self.common_dir, self.gitconfigs)
        manifest = []
        for i, (key, data) in enumerate(self.before.items()):
            source = files.get(key, self.common_dir / key)
            name = f"{i:02d}-" + re.sub(r"[^A-Za-z0-9._-]", "_", key)
            if data is None:
                manifest.append(f"{key}\t{source}\t(missing)")
                continue
            (self.backup_dir / name).write_bytes(data)
            manifest.append(f"{key}\t{source}\t{name}")
        (self.backup_dir / "MANIFEST.txt").write_text("\n".join(manifest) + "\n")

    def check(self) -> None:
        """Raise TripwireError if anything changed; otherwise drop the backup."""
        if not self.active:
            return
        assert self.backup_dir is not None
        refs = [k for k in self.before if k.startswith("refs/")]
        after = snapshot_repo_state(
            self.git_dir, self.common_dir, self.gitconfigs, refs=refs
        )
        changed = diff_repo_state(self.before, after)
        if not changed:
            shutil.rmtree(self.backup_dir, ignore_errors=True)
            return
        files = state_files(self.git_dir, self.common_dir, self.gitconfigs)
        parts = ["The test run changed real git state outside its sandbox:"]
        for key in changed:
            parts.append(f"  {key}: {files.get(key, self.common_dir / key)}")
        for key in changed:
            diff = difflib.unified_diff(
                _text(self.before[key]),
                _text(after[key]),
                fromfile=f"{key} (before)",
                tofile=f"{key} (after)",
                lineterm="",
            )
            parts.append("\n".join(diff))
        parts.append(
            f"Original contents are backed up in {self.backup_dir} "
            "(see MANIFEST.txt). Other processes may have changed these files "
            "legitimately, so compare with the backup in "
            f"{self.backup_dir} before restoring anything."
        )
        raise TripwireError("\n".join(parts))
