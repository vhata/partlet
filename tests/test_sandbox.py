"""The test session runs git in a sandbox, and notices if a real repository changes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import helpers
import pytest
from helpers import (
    Repo,
    RepoTripwire,
    TripwireError,
    diff_repo_state,
    snapshot_repo_state,
    user_gitconfig_paths,
)

from partlet.gitutil import GitError, git, git_out

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The tests that need a sandbox to pass, run again in a subprocess by
# test_sandbox_holds_inside_an_enclosing_repository. This must never include
# that test itself, or the subprocess would recurse.
SANDBOX_TESTS = [
    "test_environment_is_sandboxed",
    "test_no_inherited_git_variables",
    "test_global_git_config_is_the_sandbox_one",
    "test_repository_discovery_cannot_climb_out_of_temp",
    "test_process_cwd_is_not_a_repository",
]


def test_environment_is_sandboxed(tmp_path_factory):
    base = tmp_path_factory.getbasetemp()
    home = Path(os.environ["HOME"])
    assert home.is_dir()
    assert home.parent == base
    assert os.environ["XDG_CONFIG_HOME"] == str(home / ".config")
    assert os.environ["GIT_CONFIG_GLOBAL"] == str(home / ".gitconfig")
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    ceilings = os.environ["GIT_CEILING_DIRECTORIES"].split(":")
    assert str(base.parent) in ceilings
    assert str(base.parent.resolve()) in ceilings
    assert len(ceilings) == len(set(ceilings))


def test_no_inherited_git_variables():
    allowed = {
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CEILING_DIRECTORIES",
    }
    leaked = [k for k in os.environ if k.startswith("GIT_") and k not in allowed]
    assert leaked == []


def test_global_git_config_is_the_sandbox_one(tmp_path):
    assert git_out("config", "--global", "user.email", cwd=tmp_path) == (
        "author@example.com"
    )
    assert git_out("config", "--global", "init.defaultBranch", cwd=tmp_path) == "main"


def test_repository_discovery_cannot_climb_out_of_temp(tmp_path, tmp_path_factory):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitError):
        git("rev-parse", "--git-dir", cwd=plain)
    # Git never treats the starting directory as a ceiling, so a call made
    # directly in basetemp is the case that needs the parent as the ceiling.
    with pytest.raises(GitError):
        git("rev-parse", "--git-dir", cwd=tmp_path_factory.getbasetemp())


def test_process_cwd_is_not_a_repository(tmp_path_factory):
    assert Path.cwd().parent == tmp_path_factory.getbasetemp().resolve()
    with pytest.raises(GitError):
        git("rev-parse", "--git-dir", cwd=Path.cwd())
    with pytest.raises(GitError):
        git("rev-parse", "--git-dir", cwd=Path("."))


def test_per_test_chdir_still_works(tmp_path, monkeypatch):
    before = Path.cwd()
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path.resolve()
    monkeypatch.undo()
    assert Path.cwd() == before


def test_sandbox_holds_inside_an_enclosing_repository(tmp_path):
    # The inner run's basetemp sits inside a real repository, and git's
    # repository variables point at bogus paths. If the sandbox leaks, the
    # inner tests fail, or the outer repository changes.
    outer = tmp_path / "outer"
    outer.mkdir()
    git("init", "-q", cwd=outer)
    watched = [outer / ".git" / "config", outer / ".git" / "HEAD"]
    before = [p.read_bytes() for p in watched]

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_DIR"] = str(tmp_path / "no-such-git-dir")
    env["GIT_WORK_TREE"] = str(tmp_path / "no-such-work-tree")
    node_ids = [f"tests/test_sandbox.py::{name}" for name in SANDBOX_TESTS]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={outer / 'bt'}",
            *node_ids,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"{len(SANDBOX_TESTS)} passed" in proc.stdout
    assert [p.read_bytes() for p in watched] == before


def _snapshot(repo: Repo) -> dict[str, bytes | None]:
    git_dir = repo.path / ".git"
    return snapshot_repo_state(git_dir, git_dir, [repo.path / "no-such-gitconfig"])


def test_snapshot_reports_config_change(mono):
    mono.write("a.txt", "a")
    mono.commit("one")
    before = _snapshot(mono)
    git("config", "some.key", "value", cwd=mono.path)
    after = _snapshot(mono)
    assert diff_repo_state(before, after) == ["config"]


def test_snapshot_reports_head_ref_move(mono):
    mono.write("a.txt", "a")
    mono.commit("one")
    before = _snapshot(mono)
    mono.write("a.txt", "b")
    mono.commit("two")
    after = _snapshot(mono)
    assert diff_repo_state(before, after) == ["refs/heads/main"]


def test_snapshot_reports_gitconfig_change(tmp_path):
    gitconfig = tmp_path / "gitconfig"
    git_dir = tmp_path / "gitdir"
    git_dir.mkdir()
    before = snapshot_repo_state(git_dir, git_dir, [gitconfig])
    gitconfig.write_text("[user]\n\tname = x\n")
    after = snapshot_repo_state(git_dir, git_dir, [gitconfig])
    assert diff_repo_state(before, after) == [str(gitconfig)]


def test_snapshot_without_changes_is_equal(mono):
    mono.write("a.txt", "a")
    mono.commit("one")
    assert diff_repo_state(_snapshot(mono), _snapshot(mono)) == []


def test_snapshot_skips_refs_for_reftable(tmp_path):
    git_dir = tmp_path / "gitdir"
    git_dir.mkdir()
    (git_dir / "config").write_text("[extensions]\n\trefStorage = reftable\n")
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    state = snapshot_repo_state(git_dir, git_dir)
    assert helpers.uses_reftable(git_dir)
    assert not [k for k in state if k.startswith("refs/")]


def test_user_gitconfig_paths():
    assert user_gitconfig_paths({"GIT_CONFIG_GLOBAL": "/x/y", "HOME": "/h"}) == [
        Path("/x/y")
    ]
    assert user_gitconfig_paths({"HOME": "/h"}) == [
        Path("/h/.gitconfig"),
        Path("/h/.config/git/config"),
    ]
    assert user_gitconfig_paths({"HOME": "/h", "XDG_CONFIG_HOME": "/xdg"}) == [
        Path("/h/.gitconfig"),
        Path("/xdg/git/config"),
    ]


@pytest.fixture
def linked(tmp_path):
    """A main checkout on `main`, plus a linked worktree on `feature`."""
    main = Repo(tmp_path / "main")
    main.write("a.txt", "a")
    main.commit("one")
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feature", str(wt), cwd=main.path)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = x\n")
    backups = tmp_path / "backups"
    backups.mkdir()
    tripwire = RepoTripwire(wt, [gitconfig], backup_root=backups)
    assert tripwire.active
    assert tripwire.git_dir != tripwire.common_dir
    return main, wt, gitconfig, tripwire


def test_tripwire_clean_run_removes_backup(linked):
    *_, tripwire = linked
    backup = tripwire.backup_dir
    assert backup is not None and (backup / "MANIFEST.txt").is_file()
    tripwire.check()
    assert not backup.exists()


def test_tripwire_ignores_unrelated_branches_and_packing(linked):
    main, _, _, tripwire = linked
    git("branch", "elsewhere", cwd=main.path)
    git("pack-refs", "--all", "--prune", cwd=main.path)
    tripwire.check()


def test_tripwire_reports_config_change_with_diff_and_backup(linked):
    _, wt, _, tripwire = linked
    backup = tripwire.backup_dir
    original = (tripwire.common_dir / "config").read_bytes()
    git("config", "demo.key", "value", cwd=wt)
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    message = str(err.value)
    assert str(tripwire.common_dir / "config") in message
    assert str(backup) in message
    assert "+\tkey = value" in message
    assert "compare with the backup" in message
    assert backup is not None and backup.exists()
    assert next(backup.glob("*-config")).read_bytes() == original


def test_tripwire_reports_main_checkout_branch_move(linked):
    main, _, _, tripwire = linked
    main.write("a.txt", "b")
    main.commit("two")
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert "refs/heads/main" in str(err.value)


def test_tripwire_reports_worktree_branch_move(linked):
    _, wt, _, tripwire = linked
    git("commit", "-q", "--allow-empty", "-m", "x", cwd=wt)
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert "refs/heads/feature" in str(err.value)


def test_head_switch_does_not_report_the_old_branch(linked):
    _, wt, gitconfig, tripwire = linked
    git("switch", "-q", "-c", "other", cwd=wt)
    after = snapshot_repo_state(
        tripwire.git_dir,
        tripwire.common_dir,
        [gitconfig],
        refs=[k for k in tripwire.before if k.startswith("refs/")],
    )
    assert diff_repo_state(tripwire.before, after) == ["HEAD"]


def test_tripwire_reports_main_checkout_head_change(linked):
    main, _, _, tripwire = linked
    git("switch", "-q", "-c", "side", cwd=main.path)
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert "common-HEAD" in str(err.value)


def test_tripwire_reads_packed_refs(tmp_path):
    main = Repo(tmp_path / "main")
    main.write("a.txt", "a")
    first = main.commit("one")
    main.write("a.txt", "b")
    second = main.commit("two")
    git("pack-refs", "--all", "--prune", cwd=main.path)
    assert not (main.path / ".git" / "refs" / "heads" / "main").exists()
    tripwire = RepoTripwire(main.path, backup_root=tmp_path)
    assert tripwire.before["refs/heads/main"] == second.encode()
    packed = main.path / ".git" / "packed-refs"
    packed.write_text(packed.read_text().replace(second, first))
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert "refs/heads/main" in str(err.value)


def test_tripwire_reports_gitfile_change(linked):
    _, wt, _, tripwire = linked
    (wt / ".git").write_text("gitdir: /somewhere/else\n")
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert "gitfile" in str(err.value)


def test_tripwire_reports_user_gitconfig_change(linked):
    _, _, gitconfig, tripwire = linked
    gitconfig.write_text("[user]\n\tname = changed\n")
    with pytest.raises(TripwireError) as err:
        tripwire.check()
    assert str(gitconfig) in str(err.value)


def test_tripwire_says_when_it_is_disabled(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    tripwire = RepoTripwire(plain, backup_root=tmp_path)
    assert not tripwire.active
    assert any("DISABLED" in note for note in tripwire.notes)
    tripwire.check()


def test_tripwire_says_when_refs_are_not_watched(tmp_path, monkeypatch):
    main = Repo(tmp_path / "main")
    main.write("a.txt", "a")
    main.commit("one")
    monkeypatch.setattr(helpers, "uses_reftable", lambda common_dir: True)
    tripwire = RepoTripwire(main.path, backup_root=tmp_path)
    assert any("reftable" in note for note in tripwire.notes)
    assert not [k for k in tripwire.before if k.startswith("refs/")]
