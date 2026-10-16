"""Publishing must never change the monorepo it reads from.

Each scenario fingerprints the whole monorepo (work tree and `.git`) with plain
filesystem reads, runs a publish through the public API, and expects the same
fingerprint afterwards. Git commands are avoided in the fingerprint because
even `git status` rewrites the index.
"""

import hashlib
import os
import stat
from pathlib import Path

import pytest

from partlet.cli import main
from partlet.export import export_project
from partlet.gitutil import git
from partlet.manifest import Project, parse_manifest
from partlet.publish import publish_all
from partlet.store import LocalStore


def fingerprint(root: Path) -> dict[str, tuple[int, str]]:
    """Map every entry under `root` to its mode and sha256, using only the filesystem.

    Files hash their content, symlinks (to files or directories) hash their
    target, and directories, including `root` itself, hash nothing and record
    only their mode. Directory keys end in a slash.
    """
    empty = hashlib.sha256(b"").hexdigest()
    prints = {"./": (stat.S_IMODE(root.lstat().st_mode), empty)}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            info = path.lstat()
            key = str(path.relative_to(root))
            if stat.S_ISLNK(info.st_mode):
                digest = hashlib.sha256(os.readlink(path).encode()).hexdigest()
            elif stat.S_ISDIR(info.st_mode):
                key += "/"
                digest = empty
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            prints[key] = (stat.S_IMODE(info.st_mode), digest)
    return prints


def manifest(approved, mailmap=None):
    mailmap_line = f'mailmap = "{mailmap}"' if mailmap else ""
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"
{mailmap_line}

[projects.foo]
path = "foo"
description = "Foo tool"
approved = "{approved}"
""")


def probe_tip(mono, tmp_path, mailmap=None):
    """The tip `partlet review` would show; exporting must not change the monorepo."""
    dest = tmp_path / f"probe-{len(list(tmp_path.glob('probe-*')))}.git"
    before = fingerprint(mono.path)
    tip = export_project(mono.path, "main", Project("foo", "foo"), dest, mailmap)
    assert fingerprint(mono.path) == before
    return tip


def publish(mono, tmp_path, store, approved, mailmap=None):
    """Publish and return the result for foo; the monorepo must not change."""
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    before = fingerprint(mono.path)
    results = publish_all(mono.path, manifest(approved, mailmap), store, work)
    assert fingerprint(mono.path) == before
    return {r.name: r for r in results}["foo"]


@pytest.fixture
def published(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    return mono, LocalStore(tmp_path / "out"), probe_tip(mono, tmp_path)


def test_fingerprint_sees_changes_anywhere_in_the_repository(mono):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    base = fingerprint(mono.path)
    assert any(key.startswith(".git/objects/") for key in base)
    git("config", "user.name", "Someone Else", cwd=mono.path)
    assert fingerprint(mono.path) != base
    base = fingerprint(mono.path)
    mono.write("foo/a.txt", "two\n")
    assert fingerprint(mono.path) != base


def test_fingerprint_sees_directories_and_symlinks(mono, tmp_path):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    (mono.path / "empty").mkdir()
    (mono.path / "dirlink").symlink_to(tmp_path)
    base = fingerprint(mono.path)
    assert "empty/" in base
    assert "dirlink" in base

    (mono.path / "empty").chmod(0o700)
    changed = fingerprint(mono.path)
    assert changed != base
    (mono.path / "dirlink").unlink()
    (mono.path / "dirlink").symlink_to(mono.path)
    assert fingerprint(mono.path) != changed
    (mono.path / "empty").rmdir()
    assert "empty/" not in fingerprint(mono.path)


def test_first_publish(mono, tmp_path, published):
    mono, store, approved = published
    assert publish(mono, tmp_path, store, approved).status == "published"


def test_publish_with_the_monorepo_named_by_inherited_git_variables(
    mono, tmp_path, published, monkeypatch
):
    # The original threat: git run from a hook has GIT_DIR and GIT_WORK_TREE set
    # to the monorepo, and every git command that trusts them acts on it.
    mono, store, approved = published
    monkeypatch.setenv("GIT_DIR", str(mono.path / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(mono.path))
    monkeypatch.chdir(mono.path)
    assert publish(mono, tmp_path, store, approved).status == "published"
    assert publish(mono, tmp_path, store, approved).status == "unchanged"


def test_unchanged_rerun(mono, tmp_path, published):
    mono, store, approved = published
    publish(mono, tmp_path, store, approved)
    assert publish(mono, tmp_path, store, approved).status == "unchanged"


def test_publish_after_a_new_commit(mono, tmp_path, published):
    mono, store, approved = published
    publish(mono, tmp_path, store, approved)
    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    assert publish(mono, tmp_path, store, approved).status == "published"


def test_rejected_rewrite(mono, tmp_path, published):
    mono, store, approved = published
    publish(mono, tmp_path, store, approved)
    git(
        "commit",
        "-q",
        "--amend",
        "-m",
        "rewritten",
        cwd=mono.path,
        env={
            "GIT_COMMITTER_DATE": "1767229200 +0000",
            "GIT_AUTHOR_DATE": "1767229200 +0000",
        },
    )
    result = publish(mono, tmp_path, store, probe_tip(mono, tmp_path))
    assert result.status == "failed" and "rewrite" in result.reason


def test_missing_directory_failure(mono, tmp_path, published):
    mono, store, approved = published
    publish(mono, tmp_path, store, approved)
    mono.mv("foo", "bar")
    mono.commit("move without manifest update")
    result = publish(mono, tmp_path, store, approved)
    assert result.status == "failed" and "previous_paths" in result.reason


def test_site_with_a_mailmap_in_the_monorepo(mono, tmp_path):
    mono.write("foo/a.txt", "one\n")
    mono.write("mailmap", "Public Name <public@example.com> <author@example.com>\n")
    mono.commit("c1")
    store = LocalStore(tmp_path / "out")
    mailmapped = probe_tip(mono, tmp_path, mono.path / "mailmap")
    result = publish(mono, tmp_path, store, mailmapped, mailmap="mailmap")
    assert result.status == "published"


def test_cli_build(mono, tmp_path, published):
    mono, _store, approved = published
    mono.write(
        "partlet.toml",
        f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""",
    )
    mono.commit("add manifest")  # does not touch foo/, so the tip is unchanged
    out = tmp_path / "cli-out"
    before = fingerprint(mono.path)
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert fingerprint(mono.path) == before
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert fingerprint(mono.path) == before
