"""Prepare and verify the hosted Action smoke's synthetic, approved checkout."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from partlet.export import export_project
from partlet.gitutil import git, git_out
from partlet.manifest import Project


def prepare(root: Path) -> None:
    origin = root / "origin"
    origin.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.name", "Synthetic Author", cwd=origin)
    git("config", "user.email", "synthetic@example.com", cwd=origin)
    (origin / "foo").mkdir()
    (origin / "foo/README.md").write_text("# Foo\nSynthetic public content.\n")
    for name in ("partlet.py", "git_filter_repo.py", "jinja2.py", "sitecustomize.py"):
        (origin / name).write_text("raise RuntimeError('private module imported')\n")
    manifest = '[site]\nsource = "smoke"\nbase_url = "https://partlet.example"\n\n[projects.foo]\npath = "foo"\n'
    (origin / "partlet.toml").write_text(manifest)
    git("add", "-A", cwd=origin)
    git("commit", "-qm", "Synthetic source", cwd=origin)
    tip = export_project(origin, "main", Project("foo", "foo"), root / "probe.git")
    (origin / "partlet.toml").write_text(manifest + f'approved = "{tip}"\n')
    git("add", "partlet.toml", cwd=origin)
    git("commit", "-qm", "Approve synthetic history", cwd=origin)
    git("clone", "-q", str(origin), str(root / "mono"), cwd=root)
    git("checkout", "-q", "--detach", "origin/main", cwd=root / "mono")
    git("branch", "-q", "-D", "main", cwd=root / "mono")
    (root / "expected-tip").write_text(tip)


def verify(root: Path) -> None:
    current = json.loads((root / "site/smoke/p/foo/current").read_bytes())
    assert current["tip"] == (root / "expected-tip").read_text(), current
    assert git_out("rev-parse", "--verify", "refs/heads/main", cwd=root / "mono")
    assert (root / "site/smoke/index.json").read_text() != "[]\n"
    print("Action smoke: approved publication and detached checkout passed")


if __name__ == "__main__":
    # Git selectors and ambient Python configuration must not select user data.
    for name in tuple(os.environ):
        if name.startswith(("GIT_", "PYTHON")):
            os.environ.pop(name)
    os.environ.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, PYTHONSAFEPATH="1"
    )
    {"prepare": prepare, "verify": verify}[sys.argv[1]](Path(sys.argv[2]).resolve())
