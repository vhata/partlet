"""Keep push checks fast without weakening full validation or error handling."""

import subprocess
from pathlib import Path

import pytest
from helpers import Repo

ROOT = Path(__file__).resolve().parents[1]
STATIC = ["fmt-check", "lint", "worker-lint", "worker-typecheck"]
FULL = [*STATIC, "test", "worker-test", "worker-bundle", "worker-smoke"]


@pytest.fixture
def checkout(tmp_path):
    repo = Repo(tmp_path / "check checkout")
    for script in ("scripts/check.sh", ".githooks/pre-push"):
        repo.write(script, (ROOT / script).read_bytes())
    for gate in FULL:
        path = repo.path / f"scripts/{gate}.sh"
        repo.write(f"scripts/{gate}.sh", f"#!/bin/bash\necho {gate} >> gates.log\n")
        path.chmod(0o755)
    return repo


def run(checkout, entry="scripts/check.sh", args=()):
    return subprocess.run(
        ["bash", str(checkout.path / entry), *args],
        cwd=checkout.path / "scripts",
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize(
    "entry,args,expected",
    [
        ("scripts/check.sh", (), FULL),
        ("scripts/check.sh", ("--push",), STATIC),
        (".githooks/pre-push", ("origin", "unused-remote-url"), STATIC),
    ],
)
def test_selected_gates(checkout, entry, args, expected):
    result = run(checkout, entry, args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (checkout.path / "gates.log").read_text().splitlines() == expected


@pytest.mark.parametrize(
    "entry,args",
    [
        ("scripts/check.sh", ()),
        ("scripts/check.sh", ("--push",)),
        (".githooks/pre-push", ()),
    ],
)
def test_failure_stops_later_gates(checkout, entry, args):
    checkout.write("scripts/lint.sh", "#!/bin/bash\nexit 42\n")
    result = run(checkout, entry, args)
    assert result.returncode != 0
    assert "gate 'lint' failed" in result.stderr
    assert (checkout.path / "gates.log").read_text().splitlines() == ["fmt-check"]


@pytest.mark.parametrize("args", [(), ("--push",)])
def test_missing_static_gate_fails(checkout, args):
    (checkout.path / "scripts/worker-typecheck.sh").unlink()
    result = run(checkout, args=args)
    assert result.returncode != 0
    assert "missing or not executable" in result.stderr


@pytest.mark.parametrize("args", [("--unknown",), ("--push", "extra"), ("",)])
def test_invalid_arguments_fail_before_running_gates(checkout, args):
    result = run(checkout, args=args)
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert not (checkout.path / "gates.log").exists()
