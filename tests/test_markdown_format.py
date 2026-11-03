"""Exercise the formatter against real Git indexes and working copies."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import Repo
from markdown_it import MarkdownIt

from partlet.gitutil import git, git_out

ROOT = Path(__file__).resolve().parents[1]
UNFORMATTED = "# Heading\n\n\nText.\n"
FORMATTED = "# Heading\n\nText.\n"


@pytest.fixture
def repo(tmp_path):
    repo = Repo(tmp_path / "format checkout")
    repo.write(".gitignore", ".venv/\n")
    repo.write(
        "scripts/fmt-markdown.sh", (ROOT / "scripts/fmt-markdown.sh").read_bytes()
    )
    repo.write(".mdformat.toml", (ROOT / ".mdformat.toml").read_bytes())
    # Reuse only the tools; all Git operations target this disposable repo.
    (repo.path / ".venv").symlink_to(Path(sys.executable).parent.parent)
    repo.commit("Formatter fixture")
    return repo


def run_formatter(repo, *args):
    return subprocess.run(
        ["bash", str(repo.path / "scripts/fmt-markdown.sh"), *args],
        cwd=repo.path / "scripts",
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_write_check_scope_and_idempotence(repo):
    names = [
        "README.md",
        "-dash.MD",
        "docs/spaced name.markdown",
        ".github/template.md",
    ]
    for name in names + ["docket/CONTRACT.md", "removed.md", "target.txt"]:
        repo.write(name, UNFORMATTED)
    repo.symlink("linked.md", "target.txt")
    repo.commit("Documents")
    repo.write("untracked.md", UNFORMATTED)
    (repo.path / "removed.md").unlink()

    assert run_formatter(repo, "--check").returncode == 1
    assert (repo.path / "README.md").read_text() == UNFORMATTED
    result = run_formatter(repo)
    assert result.returncode == 0, result.stderr
    for name in names:
        assert (repo.path / name).read_text() == FORMATTED
    for name in ["docket/CONTRACT.md", "untracked.md", "target.txt"]:
        assert (repo.path / name).read_text() == UNFORMATTED
    assert (repo.path / "linked.md").is_symlink()
    assert not (repo.path / "removed.md").exists()
    assert run_formatter(repo, "--check").returncode == 0
    before = git_out("diff", cwd=repo.path)
    assert run_formatter(repo).returncode == 0
    assert git_out("diff", cwd=repo.path) == before


def test_staged_rewrite_stops_without_staging(repo):
    repo.write("new file.md", UNFORMATTED)
    repo.write("unrelated.md", UNFORMATTED)
    git("add", "new file.md", cwd=repo.path)
    index = git_out("write-tree", cwd=repo.path)

    result = run_formatter(repo, "--staged")

    assert result.returncode == 1
    assert "review and stage it again" in result.stderr
    assert (repo.path / "new file.md").read_text() == FORMATTED
    assert (repo.path / "unrelated.md").read_text() == UNFORMATTED
    assert git_out("write-tree", cwd=repo.path) == index
    git("add", "new file.md", cwd=repo.path)
    assert run_formatter(repo, "--staged").returncode == 0


@pytest.mark.parametrize("working", [FORMATTED, "Unstaged text.\n", None])
def test_partial_staging_never_overwrites_work_or_index(repo, working):
    repo.write("README.md", UNFORMATTED)
    git("add", "README.md", cwd=repo.path)
    if working is None:
        (repo.path / "README.md").unlink()
    else:
        repo.write("README.md", working)
    index = git_out("write-tree", cwd=repo.path)

    result = run_formatter(repo, "--staged")

    assert result.returncode == 1
    assert "unstaged changes" in result.stderr
    assert git_out("write-tree", cwd=repo.path) == index
    if working is None:
        assert not (repo.path / "README.md").exists()
    else:
        assert (repo.path / "README.md").read_text() == working


def test_formatted_partial_stage_and_renames_deletions_symlinks(repo):
    repo.write("old.md", FORMATTED)
    repo.write("deleted.md", UNFORMATTED)
    repo.commit("Initial documents")
    repo.mv("old.md", "renamed.md")
    repo.rm("deleted.md")
    repo.symlink("linked.md", "renamed.md")
    git("add", "linked.md", cwd=repo.path)
    repo.write("renamed.md", UNFORMATTED)
    index = git_out("write-tree", cwd=repo.path)

    assert run_formatter(repo, "--staged").returncode == 0
    assert git_out("write-tree", cwd=repo.path) == index
    assert (repo.path / "renamed.md").read_text() == UNFORMATTED
    assert (repo.path / "linked.md").is_symlink()


def test_gfm_wrap_and_queue_compatibility(repo):
    source = (
        "# Queue\n\n- [TOOLING] `example` A formatter integration task\n"
        "  - Source: direct request\n"
        "  - Acceptance: " + "several words " * 15 + "\n\n"
        "- [x] A completed task\n\n| Name | State |\n|---|---|\n| Task | Done |\n\n"
        "<!-- preserved comment -->\n\n```sh\necho 'unchanged'\n```\n"
    )
    repo.write("README.md", source)
    git("add", "README.md", cwd=repo.path)
    assert run_formatter(repo).returncode == 0
    formatted = (repo.path / "README.md").read_text()
    assert "- [TOOLING] `example`" in formatted
    assert "  - Source: direct request\n" in formatted
    assert "  - Acceptance: " in formatted
    assert "- [x] A completed task" in formatted
    html = MarkdownIt("commonmark").enable("table").render(formatted)
    assert "<th>Name</th>" in html
    assert "<td>Done</td>" in html
    assert "<!-- preserved comment -->" in formatted
    assert "```sh\necho 'unchanged'\n```" in formatted
    assert all(len(line) <= 72 for line in formatted.splitlines())
    # The staged stdin path uses the same root config as file formatting.
    git("add", "README.md", cwd=repo.path)
    assert run_formatter(repo, "--staged").returncode == 0
    assert run_formatter(repo, "--check").returncode == 0


@pytest.mark.parametrize("path", ["AGENTS.md", "TODO.md", "review/BACKLOG.md"])
def test_docket_fields_stay_on_single_lines(repo, path):
    if path == "AGENTS.md":
        source = (ROOT / "AGENTS.md").read_text()
        block = source.split("<!-- docket:begin -->")[1].split("<!-- docket:end -->")[0]
    else:
        source = (
            "# Queue\n\n## Ready for separate work\n\n### P2 Normal\n\n"
            if path == "TODO.md"
            else "# Review backlog\n\n## P2 Normal\n\n"
        )
        source += (
            "- [TOOLING] `long-outcome` **Automatically format every Markdown document "
            "while preserving staged content and local edits.** Keep queues compatible.\n"
            "  - Source: direct request\n"
        )
        if path == "review/BACKLOG.md":
            source += "  - Findings: `long-outcome-finding`\n"
    repo.write(path, source)
    git("add", path, cwd=repo.path)

    assert run_formatter(repo).returncode == 0
    formatted = (repo.path / path).read_text()
    if path == "AGENTS.md":
        assert (
            formatted.split("<!-- docket:begin -->")[1].split("<!-- docket:end -->")[0]
            == block
        )
    else:
        validator = repo.path / "docket/scripts/check-queues.sh"
        validator.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "docket/scripts/check-queues.sh", validator)
        result = subprocess.run(
            ["bash", str(validator), "--strict"],
            cwd=repo.path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    git("add", path, cwd=repo.path)
    assert run_formatter(repo, "--staged").returncode == 0
    assert run_formatter(repo, "--check").returncode == 0
