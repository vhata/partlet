import pytest

from partlet.export import export_project
from partlet.gitutil import git_out
from partlet.history import HistoryError, check_history, is_ancestor
from partlet.manifest import Project


@pytest.fixture
def chain(mono, tmp_path):
    """An export with three commits; returns (repo, [c1, c2, c3])."""
    for i in range(3):
        mono.write("foo/a.txt", f"{i}\n")
        mono.commit(f"c{i}")
    repo = tmp_path / "e.git"
    export_project(mono.path, "main", Project("foo", "foo"), repo)
    shas = git_out("rev-list", "--reverse", "refs/heads/main", cwd=repo).splitlines()
    return repo, shas


def test_is_ancestor(chain):
    repo, (c1, _c2, c3) = chain
    assert is_ancestor(repo, c1, c3)
    assert not is_ancestor(repo, c3, c1)
    assert not is_ancestor(repo, "f" * 40, c3)


def test_first_publish_requires_approved_ancestor(chain):
    repo, (_c1, c2, c3) = chain
    assert check_history(repo, c3, None, c2, None).action == "publish"
    assert check_history(repo, c3, None, c3, None).action == "publish"
    with pytest.raises(HistoryError, match="approved"):
        check_history(repo, c3, None, "f" * 40, None)


def test_not_approved_is_an_error(chain):
    repo, (_c1, _c2, c3) = chain
    with pytest.raises(HistoryError, match="not approved"):
        check_history(repo, c3, None, None, None)


def test_fast_forward_publishes(chain):
    repo, (c1, c2, c3) = chain
    assert check_history(repo, c3, c2, c1, None).action == "publish"


def test_same_tip_is_unchanged(chain):
    repo, (c1, _c2, c3) = chain
    assert check_history(repo, c3, c3, c1, None).action == "unchanged"


def test_non_fast_forward_is_rejected(chain):
    repo, (c1, c2, c3) = chain
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c3, "e" * 40, c1, None)
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c2, c3, c1, None)


def test_allow_rewrite_of_permits_exactly_that_tip(chain):
    repo, (_c1, _c2, c3) = chain
    old = "e" * 40
    assert check_history(repo, c3, old, c3, old).action == "rewrite"
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c3, old, c3, "d" * 40)


def test_allow_rewrite_still_requires_approval_ancestry(chain):
    repo, (_c1, _c2, c3) = chain
    old = "e" * 40
    with pytest.raises(HistoryError, match="approved"):
        check_history(repo, c3, old, "f" * 40, old)
