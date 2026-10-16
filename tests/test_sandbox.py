"""The test session runs git in a sandbox, and notices if a real repository changes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from helpers import Repo, diff_repo_state, snapshot_repo_state

from partlet.gitutil import GitError, git, git_out


def test_environment_is_sandboxed(tmp_path_factory):
    home = Path(os.environ["HOME"])
    assert home.is_dir()
    assert home.parent == tmp_path_factory.getbasetemp()
    assert os.environ["XDG_CONFIG_HOME"] == str(home / ".config")
    assert os.environ["GIT_CONFIG_GLOBAL"] == str(home / ".gitconfig")
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    ceilings = os.environ["GIT_CEILING_DIRECTORIES"].split(":")
    assert str(tmp_path_factory.getbasetemp()) in ceilings
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


def test_repository_discovery_cannot_climb_out_of_temp(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitError):
        git("rev-parse", "--git-dir", cwd=plain)


def _snapshot(repo: Repo) -> dict[str, bytes | None]:
    git_dir = repo.path / ".git"
    return snapshot_repo_state(git_dir, git_dir, repo.path / "no-such-gitconfig")


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
    before = snapshot_repo_state(git_dir, git_dir, gitconfig)
    gitconfig.write_text("[user]\n\tname = x\n")
    after = snapshot_repo_state(git_dir, git_dir, gitconfig)
    assert diff_repo_state(before, after) == ["gitconfig"]


def test_snapshot_without_changes_is_equal(mono):
    mono.write("a.txt", "a")
    mono.commit("one")
    assert diff_repo_state(_snapshot(mono), _snapshot(mono)) == []
