from pathlib import Path

import pytest

import partlet.export
from partlet.export import ExportError, check_export_repo, export_project
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


def test_move_of_names_that_need_quoting_still_fast_forwards(mono, tmp_path):
    mono.write("scripts/foo/a b.txt", "one\n")
    mono.commit("c1")
    before = export_project(
        mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "before.git"
    )

    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    mono.write("tools/foo/a b.txt", "one\ntwo\n")
    mono.commit("c2")
    moved = Project("foo", "tools/foo", previous_paths=("scripts/foo",))
    after = export_project(mono.path, "main", moved, tmp_path / "after.git")

    # filter-repo keeps the move as an empty commit here (see docs/DECISIONS.md),
    # so only ancestry is asserted.
    git("merge-base", "--is-ancestor", before, after, cwd=tmp_path / "after.git")


def test_merged_side_branch_keeps_project_commits(mono, tmp_path):
    mono.write("tools/foo/a.txt", "one\n")
    mono.write("other/x.txt", "x\n")
    mono.commit("c1")
    git("checkout", "-q", "-b", "side", cwd=mono.path)
    mono.write("tools/foo/b.txt", "side\n")
    mono.commit("s1 touches foo")
    mono.write("tools/foo/b.txt", "side\nmore\n")
    mono.commit("s2 touches foo")
    git("checkout", "-q", "main", cwd=mono.path)
    mono.write("other/x.txt", "x\ny\n")
    mono.commit("m1 only other")
    date = "1767232800 +0000"
    git(
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "merge side",
        "side",
        cwd=mono.path,
        env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
    )
    mono.write("other/x.txt", "x\ny\nz\n")
    mono.commit("m2 only other")

    project = Project("foo", "tools/foo")
    a = export_project(mono.path, "main", project, tmp_path / "a.git")
    b = export_project(mono.path, "main", project, tmp_path / "b.git")
    assert a == b
    repo = tmp_path / "a.git"
    found = subjects(repo)
    assert {"c1", "s1 touches foo", "s2 touches foo"} <= set(found)
    assert "m1 only other" not in found
    assert "m2 only other" not in found
    assert files_at(repo) == ["a.txt", "b.txt"]


def test_deleted_file_is_gone_at_tip_but_kept_in_history(mono, tmp_path):
    mono.write("foo/a.txt", "a\n")
    mono.write("foo/gone.txt", "soon gone\n")
    mono.commit("c1")
    mono.rm("foo/gone.txt")
    mono.commit("c2 deletes gone.txt")
    export_project(mono.path, "main", Project("foo", "foo"), tmp_path / "e.git")
    repo = tmp_path / "e.git"
    assert files_at(repo) == ["a.txt"]
    assert files_at(repo, "refs/heads/main~1") == ["a.txt", "gone.txt"]


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


@pytest.mark.parametrize("tag_has_project", [False, True])
def test_export_uses_branch_directory_despite_same_named_tag(
    mono, tmp_path, tag_has_project
):
    mono.write("other.txt", "outside the project\n")
    if tag_has_project:
        mono.write("foo/a.txt", "tag contents\n")
    mono.commit("tagged snapshot")
    git("tag", "main", cwd=mono.path)
    mono.write("foo/a.txt", "branch contents\n")
    mono.commit("project on branch")

    dest = tmp_path / "e.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), dest)

    assert files_at(dest) == ["a.txt"]
    assert git_out("show", f"{tip}:a.txt", cwd=dest) == "branch contents"


@pytest.mark.parametrize(
    ("branch_path", "message"),
    [("missing", "does not exist on main"), ("file", "not a directory")],
)
def test_export_rejects_branch_path_despite_same_named_tag_directory(
    mono, tmp_path, branch_path, message
):
    mono.write("foo/a.txt", "tag contents\n")
    mono.write("other.txt", "outside the project\n")
    mono.commit("tagged directory")
    git("tag", "main", cwd=mono.path)
    mono.rm("foo")
    if branch_path == "file":
        mono.write("foo", "branch file\n")
    mono.commit("project removed from branch")

    dest = tmp_path / "new" / "e.git"
    with pytest.raises(ExportError, match=message):
        export_project(mono.path, "main", Project("foo", "foo"), dest)
    assert not dest.parent.exists()


def test_export_rejects_a_tag_without_a_branch(mono, tmp_path):
    mono.write("foo/a.txt", "tag contents\n")
    mono.commit("tagged directory")
    git("tag", "release", cwd=mono.path)

    dest = tmp_path / "new" / "e.git"
    with pytest.raises(ExportError, match="branch 'release' not found"):
        export_project(mono.path, "release", Project("foo", "foo"), dest)
    assert not dest.parent.exists()


def test_export_checks_the_destination_before_each_mutating_step(tmp_path, monkeypatch):
    from helpers import Repo

    mono = Repo(tmp_path / "mono", branch="trunk")
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    events: list[tuple[str, ...]] = []

    def spy(name, real):
        def wrapper(*args, **kwargs):
            events.append((name, *args[:1]) if name == "git" else (name,))
            return real(*args, **kwargs)

        return wrapper

    for name in ("check_export_repo", "run_filter_repo", "git"):
        monkeypatch.setattr(
            partlet.export, name, spy(name, getattr(partlet.export, name))
        )
    export_project(mono.path, "trunk", Project("foo", "foo"), tmp_path / "e.git")

    names = [e[0] for e in events]
    filter_at = names.index("run_filter_repo")
    assert "check_export_repo" in names[:filter_at]
    mutating = [
        i
        for i, e in enumerate(events)
        if e in {("git", "branch"), ("git", "symbolic-ref")}
    ]
    assert mutating, "expected branch -m / symbolic-ref to run"
    assert "check_export_repo" in names[filter_at + 1 : mutating[0]]


def test_missing_directory_fails_with_hint(mono, tmp_path):
    mono.write("scripts/foo/a.txt", "a\n")
    mono.commit("c1")
    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    with pytest.raises(ExportError, match="previous_paths"):
        export_project(
            mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "e.git"
        )


def test_missing_branch_fails_with_branch_message(mono, tmp_path):
    make_basic(mono)
    with pytest.raises(ExportError, match="branch") as info:
        export_project(
            mono.path, "nope", Project("foo", "tools/foo"), tmp_path / "e.git"
        )
    assert "previous_paths" not in str(info.value)


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


def test_relative_dest_is_relative_to_the_caller(mono, tmp_path, monkeypatch):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    monkeypatch.chdir(tmp_path)
    export_project(mono.path, "main", Project("foo", "foo"), Path("e.git"))
    assert files_at(tmp_path / "e.git") == ["a.txt"]
    assert not (mono.path / "e.git").exists()


def test_existing_destination_is_refused(mono, tmp_path):
    make_basic(mono)
    dest = tmp_path / "e.git"
    dest.mkdir()
    with pytest.raises(ExportError, match="already exists"):
        export_project(mono.path, "main", Project("foo", "tools/foo"), dest)
    assert list(dest.iterdir()) == []


def fresh_export_clone(mono, dest):
    git(
        "clone",
        "--quiet",
        "--bare",
        "--no-local",
        "--no-tags",
        "--single-branch",
        "--branch",
        "main",
        str(mono.path),
        str(dest),
        cwd=dest.parent,
    )


def test_export_survives_a_renamed_default_remote(mono, tmp_path, monkeypatch):
    # filter-repo's fresh-clone check wants exactly one remote, named origin.
    make_basic(mono)
    config = tmp_path / "gitconfig"
    config.write_text("[clone]\n\tdefaultRemoteName = upstream\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    export_project(mono.path, "main", Project("foo", "tools/foo"), tmp_path / "e.git")
    assert files_at(tmp_path / "e.git") == ["a.txt"]


def test_check_export_repo_accepts_a_fresh_bare_clone(mono, tmp_path):
    make_basic(mono)
    dest = tmp_path / "e.git"
    fresh_export_clone(mono, dest)
    check_export_repo(dest, mono.path)  # does not raise


def test_check_export_repo_rejects_a_work_tree_and_the_monorepo_itself(mono, tmp_path):
    make_basic(mono)
    config = mono.path / ".git" / "config"
    before = config.read_bytes()
    for bad in (mono.path, mono.path / ".git", mono.path / "tools" / "foo"):
        with pytest.raises(ExportError, match="not a bare repository"):
            check_export_repo(bad, mono.path)
    assert config.read_bytes() == before


def test_check_export_repo_rejects_a_directory_outside_any_repository(mono, tmp_path):
    make_basic(mono)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ExportError, match="cannot inspect"):
        check_export_repo(plain, mono.path)
    with pytest.raises(ExportError, match="cannot inspect"):
        check_export_repo(tmp_path / "missing", mono.path)


def test_check_export_repo_rejects_a_directory_that_git_climbs_out_of(mono, tmp_path):
    # From a plain directory inside a bare repository, git finds the repository
    # above it, so a mutating command run there would hit that repository.
    make_basic(mono)
    real = tmp_path / "real.git"
    fresh_export_clone(mono, real)
    with pytest.raises(ExportError, match="resolves to"):
        check_export_repo(real / "refs", mono.path)


def test_check_export_repo_rejects_a_repo_that_borrows_a_common_dir(mono, tmp_path):
    make_basic(mono)
    other = tmp_path / "other.git"
    dest = tmp_path / "e.git"
    fresh_export_clone(mono, other)
    fresh_export_clone(mono, dest)
    (dest / "commondir").write_text(f"{other}\n")
    with pytest.raises(ExportError, match="common dir"):
        check_export_repo(dest, mono.path)


def test_check_export_repo_rejects_a_bare_monorepo_itself(mono, tmp_path):
    make_basic(mono)
    real = tmp_path / "real.git"
    fresh_export_clone(mono, real)
    with pytest.raises(ExportError, match="monorepo's own"):
        check_export_repo(real, real)


def test_check_export_repo_rejects_the_bare_repo_behind_a_linked_worktree(
    mono, tmp_path
):
    make_basic(mono)
    real = tmp_path / "real.git"
    fresh_export_clone(mono, real)
    linked = tmp_path / "linked"
    git("worktree", "add", "--quiet", "--detach", str(linked), "main", cwd=real)
    config = real / "config"
    before = config.read_bytes()
    with pytest.raises(ExportError, match="monorepo's own"):
        check_export_repo(real, linked)
    assert config.read_bytes() == before


def test_check_export_repo_rejects_a_bare_repo_inside_the_monorepo(mono, tmp_path):
    make_basic(mono)
    dest = mono.path / "nested.git"
    fresh_export_clone(mono, dest)
    with pytest.raises(ExportError, match="inside the monorepo"):
        check_export_repo(dest, mono.path)


def test_check_export_repo_knows_the_monorepo_top_level_from_a_subdirectory(
    mono, tmp_path
):
    make_basic(mono)
    dest = mono.path / "other" / "nested.git"
    dest.parent.mkdir(exist_ok=True)
    fresh_export_clone(mono, dest)
    with pytest.raises(ExportError, match="inside the monorepo"):
        check_export_repo(dest, mono.path / "tools" / "foo")


def swapped_case(path: Path) -> Path:
    other = Path(str(path).swapcase())
    if not other.exists():
        pytest.skip("case-sensitive filesystem")
    return other


def test_check_export_repo_inside_check_ignores_path_case(mono, tmp_path):
    make_basic(mono)
    dest = mono.path / "nested.git"
    fresh_export_clone(mono, dest)
    with pytest.raises(ExportError, match="inside the monorepo"):
        check_export_repo(swapped_case(dest), mono.path)
    with pytest.raises(ExportError, match="inside the monorepo"):
        check_export_repo(dest, swapped_case(mono.path))


def test_destination_inside_the_monorepo_is_refused_before_anything_is_written(
    mono, tmp_path
):
    make_basic(mono)
    dest = mono.path / "new" / "e.git"
    with pytest.raises(ExportError, match="inside the monorepo"):
        export_project(mono.path, "main", Project("foo", "tools/foo"), dest)
    assert not (mono.path / "new").exists()


def test_destination_inside_the_monorepo_is_refused_whatever_its_case(mono, tmp_path):
    make_basic(mono)
    dest = swapped_case(mono.path) / "new" / "e.git"
    with pytest.raises(ExportError, match="inside the monorepo"):
        export_project(mono.path, "main", Project("foo", "tools/foo"), dest)
    assert not (mono.path / "new").exists()


def test_git_path_rejects_output_from_a_git_without_path_format(monkeypatch):
    # Before git 2.31, rev-parse echoes the unknown flag back and exits 0.
    monkeypatch.setattr(
        partlet.export, "git_out", lambda *a, **k: "--path-format=absolute\n/some/path"
    )
    with pytest.raises(
        ExportError, match=r"git 2\.31 or newer.*--path-format=absolute"
    ):
        partlet.export._git_path("--git-common-dir", cwd=Path("/x"))
