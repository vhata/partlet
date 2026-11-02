import importlib.metadata
import tomllib
from pathlib import Path

import pytest

from partlet import tools
from partlet.scan import GITLEAKS_VERSION
from partlet.tools import FILTER_REPO_VERSION, ToolError, check_tools

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_pins_filter_repo_exactly():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert f"git-filter-repo=={FILTER_REPO_VERSION}" in deps


def test_check_tools_reports_pinned_versions():
    found = check_tools(gitleaks=True)
    assert found.versions["git-filter-repo"] == FILTER_REPO_VERSION
    assert found.versions["gitleaks"] == GITLEAKS_VERSION
    assert found.versions["git"][0].isdigit()
    assert found.gitleaks is not None


def test_other_filter_repo_release_is_refused(monkeypatch):
    real = importlib.metadata.version
    monkeypatch.setattr(
        tools.importlib.metadata,
        "version",
        lambda name: "2.38.0" if name == "git-filter-repo" else real(name),
    )
    with pytest.raises(ToolError, match=f"exactly {FILTER_REPO_VERSION}"):
        check_tools(gitleaks=False)


def test_old_git_is_refused(monkeypatch):
    monkeypatch.setattr(tools, "git_out", lambda *a, **k: "git version 2.30.8")
    with pytest.raises(ToolError, match="2.31 or newer"):
        check_tools(gitleaks=False)


def test_missing_git_is_a_tool_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(tools, "git_out", missing)
    with pytest.raises(ToolError, match="cannot run git"):
        check_tools(gitleaks=False)
