from helpers import Repo

from partlet.gitutil import git, git_out


def test_inherited_repository_variables_do_not_redirect_git(tmp_path, monkeypatch):
    # Git exports GIT_DIR and friends to hooks; a partlet run from a hook
    # must still operate on the repository named by cwd.
    target = Repo(tmp_path / "target")
    bystander = Repo(tmp_path / "bystander")
    monkeypatch.setenv("GIT_DIR", str(bystander.path / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(bystander.path))
    monkeypatch.setenv("GIT_INDEX_FILE", str(bystander.path / ".git" / "index"))

    assert git_out("rev-parse", "--absolute-git-dir", cwd=target.path) == str(
        (target.path / ".git").resolve()
    )
    git("config", "partlet.probe", "yes", cwd=target.path)
    config = (bystander.path / ".git" / "config").read_text()
    assert "probe" not in config
