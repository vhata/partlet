import pytest

from partlet.export import ExportError, export_project
from partlet.gitutil import git, git_out
from partlet.manifest import Project


def files_at(repo, rev="refs/heads/main"):
    return sorted(git_out("ls-tree", "-r", "--name-only", rev, cwd=repo).splitlines())


def subjects(repo):
    return git_out("log", "--format=%s", "refs/heads/main", cwd=repo).splitlines()


def make_basic(mono):
    mono.write("tools/foo/a.txt", "one\n")
    mono.write("tools/foobar/b.txt", "neighbour\n")
    mono.write("other/x.txt", "x\n")
    mono.commit("c1")
    mono.write("tools/foo/a.txt", "one\ntwo\n")
    mono.commit("c2 touches foo")
    mono.write("other/x.txt", "x\ny\n")
    mono.commit("c3 only other")


def test_export_keeps_only_project_files_at_root(mono, tmp_path):
    make_basic(mono)
    tip = export_project(
        mono.path, "main", Project("foo", "tools/foo"), tmp_path / "e.git"
    )
    repo = tmp_path / "e.git"
    assert files_at(repo) == ["a.txt"]
    assert subjects(repo) == ["c2 touches foo", "c1"]
    assert git_out("rev-parse", "refs/heads/main", cwd=repo) == tip
    assert git_out("symbolic-ref", "HEAD", cwd=repo) == "refs/heads/main"
    refs = git_out("for-each-ref", "--format=%(refname)", cwd=repo).splitlines()
    assert refs == ["refs/heads/main"]


def test_export_is_deterministic(mono, tmp_path):
    make_basic(mono)
    a = export_project(
        mono.path, "main", Project("foo", "tools/foo"), tmp_path / "a.git"
    )
    b = export_project(
        mono.path, "main", Project("foo", "tools/foo"), tmp_path / "b.git"
    )
    assert a == b


def test_move_with_previous_paths_fast_forwards(mono, tmp_path):
    mono.write("scripts/foo/a.txt", "one\n")
    mono.commit("c1")
    mono.write("scripts/foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    before = export_project(
        mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "before.git"
    )

    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    mono.write("tools/foo/a.txt", "one\ntwo\nthree\n")
    mono.commit("c3")
    moved = Project("foo", "tools/foo", previous_paths=("scripts/foo",))
    after = export_project(mono.path, "main", moved, tmp_path / "after.git")

    repo = tmp_path / "after.git"
    git("merge-base", "--is-ancestor", before, after, cwd=repo)  # raises if not
    assert subjects(repo) == ["c3", "c2", "c1"]  # the move commit is pruned


def test_branch_is_renamed_to_main(tmp_path):
    from helpers import Repo

    mono = Repo(tmp_path / "mono", branch="trunk")
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    export_project(mono.path, "trunk", Project("foo", "foo"), tmp_path / "e.git")
    refs = git_out(
        "for-each-ref", "--format=%(refname)", cwd=tmp_path / "e.git"
    ).splitlines()
    assert refs == ["refs/heads/main"]


def test_missing_directory_fails_with_hint(mono, tmp_path):
    mono.write("scripts/foo/a.txt", "a\n")
    mono.commit("c1")
    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    with pytest.raises(ExportError, match="previous_paths"):
        export_project(
            mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "e.git"
        )


def test_path_that_is_a_file_fails(mono, tmp_path):
    mono.write("foo", "i am a file\n")
    mono.commit("c1")
    with pytest.raises(ExportError, match="not a directory"):
        export_project(mono.path, "main", Project("foo", "foo"), tmp_path / "e.git")


def test_shallow_monorepo_is_rejected(mono, tmp_path):
    make_basic(mono)
    shallow = tmp_path / "shallow"
    git(
        "clone", "-q", "--depth", "1", f"file://{mono.path}", str(shallow), cwd=tmp_path
    )
    with pytest.raises(ExportError, match="shallow"):
        export_project(shallow, "main", Project("foo", "tools/foo"), tmp_path / "e.git")


def test_mailmap_rewrites_author(mono, tmp_path):
    make_basic(mono)
    mailmap = tmp_path / "mailmap"
    mailmap.write_text("Public Name <public@example.com> <author@example.com>\n")
    export_project(
        mono.path, "main", Project("foo", "tools/foo"), tmp_path / "e.git", mailmap
    )
    authors = set(
        git_out(
            "log", "--format=%an <%ae>", "refs/heads/main", cwd=tmp_path / "e.git"
        ).splitlines()
    )
    assert authors == {"Public Name <public@example.com>"}
