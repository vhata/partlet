"""Exercise the actual Python gate against disposable pytest projects."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import Repo

ROOT = Path(__file__).resolve().parents[1]
NO_EXECUTION = "test: no test cases executed; wholly skipped suite"


@pytest.fixture
def gate_project(tmp_path):
    root = tmp_path / "gate project"
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    shutil.copyfile(ROOT / "scripts/test.sh", root / "scripts/test.sh")
    shutil.copyfile(ROOT / "tests/pytest_gate.py", root / "tests/pytest_gate.py")
    # Use this worktree's interpreter/dependencies, without installing into
    # the disposable project or involving any real repository's test hooks.
    (root / ".venv").symlink_to(
        Path(sys.executable).parent.parent, target_is_directory=True
    )
    (root / "pytest.ini").write_text("[pytest]\n")
    return root


def run_gate(root, source, *args, env=None):
    # An explicitly selected file outside tests/ also has to enforce the
    # gate: pytest would not load tests/conftest.py for such a selection.
    selected = root / "selected.py"
    selected.write_text(source)
    return subprocess.run(
        ["bash", "scripts/test.sh", str(selected), *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n@pytest.mark.skip\ndef test_case(): pass\n",
        "import pytest\ndef test_case(): pytest.skip('runtime')\n",
        (
            "import pytest\n@pytest.fixture\ndef dependency(): pytest.skip('setup')\n"
            "def test_case(dependency): pass\n"
        ),
        "import pytest\n@pytest.mark.xfail(run=False)\ndef test_case(): assert False\n",
        (
            "import pytest\n@pytest.fixture\ndef dependency(): pytest.xfail('setup')\n"
            "def test_case(dependency): pass\n"
        ),
    ],
    ids=["mark", "runtime", "fixture", "xfail-not-run", "xfail-setup"],
)
def test_wholly_skipped_suite_fails(gate_project, source):
    proc = run_gate(gate_project, source)
    assert proc.returncode == pytest.ExitCode.TESTS_FAILED, proc.stdout + proc.stderr
    assert NO_EXECUTION in proc.stderr


@pytest.mark.parametrize(
    "source",
    [
        (
            "import pytest\n@pytest.mark.skip\ndef test_skip(): pass\n"
            "def test_pass(): assert 1 + 1 == 2\n"
        ),
        "import pytest\n@pytest.mark.xfail\ndef test_case(): assert False\n",
        "import pytest\ndef test_case(): pytest.xfail('expected')\n",
        "import pytest\n@pytest.mark.xfail\ndef test_case(): pass\n",
    ],
    ids=["mixed", "xfail-executed", "runtime-xfail", "xpass"],
)
def test_executed_case_satisfies_the_gate(gate_project, source):
    proc = run_gate(gate_project, source)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert NO_EXECUTION not in proc.stderr


@pytest.mark.parametrize(
    "source, arguments, expected",
    [
        ("def test_case(): assert False\n", (), pytest.ExitCode.TESTS_FAILED),
        (
            (
                "import pytest\n@pytest.fixture\ndef dependency(): raise RuntimeError('setup')\n"
                "def test_case(dependency): pass\n"
            ),
            (),
            pytest.ExitCode.TESTS_FAILED,
        ),
        ("raise RuntimeError('collection')\n", (), pytest.ExitCode.INTERRUPTED),
        ("def test_case(): raise KeyboardInterrupt\n", (), pytest.ExitCode.INTERRUPTED),
        ("", (), pytest.ExitCode.NO_TESTS_COLLECTED),
        (
            "import pytest\npytest.skip('module', allow_module_level=True)\n",
            (),
            pytest.ExitCode.NO_TESTS_COLLECTED,
        ),
        (
            "def test_case(): pass\n",
            ("-k", "missing"),
            pytest.ExitCode.NO_TESTS_COLLECTED,
        ),
        (
            "def test_case(): pass\n",
            ("--nonexistent-option",),
            pytest.ExitCode.USAGE_ERROR,
        ),
        (
            "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_case(): pass\n",
            (),
            pytest.ExitCode.TESTS_FAILED,
        ),
    ],
    ids=[
        "failure",
        "setup",
        "collection",
        "interrupt",
        "empty",
        "module-skip",
        "deselected",
        "usage",
        "strict-xpass",
    ],
)
def test_existing_failure_status_is_preserved(
    gate_project, source, arguments, expected
):
    proc = run_gate(gate_project, source, *arguments)
    assert proc.returncode == expected, proc.stdout + proc.stderr
    assert NO_EXECUTION not in proc.stderr


@pytest.mark.parametrize(
    "source",
    [
        "def test_case(): pass\n",
        "import pytest\n@pytest.mark.skip\ndef test_case(): pass\n",
        "import pytest\n@pytest.mark.xfail(run=False)\ndef test_case(): pass\n",
    ],
    ids=["ordinary", "skip", "xfail-not-run"],
)
@pytest.mark.parametrize(
    "option",
    [
        "--collect-only",
        "--setup-plan",
        "--setup-only",
        "--fixtures",
        "--fixtures-per-test",
    ],
)
def test_inspection_mode_remains_successful(gate_project, source, option):
    proc = run_gate(gate_project, source, option)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    if option == "--collect-only":
        assert "1 test collected" in proc.stdout
    assert NO_EXECUTION not in proc.stderr


def test_other_plugin_failure_status_is_preserved(gate_project):
    (gate_project / "conftest.py").write_text(
        "def pytest_sessionfinish(session): session.exitstatus = 7\n"
    )
    proc = run_gate(
        gate_project, "import pytest\n@pytest.mark.skip\ndef test_case(): pass\n"
    )
    assert proc.returncode == 7, proc.stdout + proc.stderr
    assert NO_EXECUTION not in proc.stderr


def test_gate_preserves_real_tripwire_diagnostic(gate_project, tmp_path):
    repo = Repo(gate_project / "sandbox")
    (repo.path / "tests").mkdir()
    for name in ("conftest.py", "helpers.py"):
        shutil.copyfile(ROOT / "tests" / name, repo.path / "tests" / name)
    (repo.path / "pytest.ini").write_text("[pytest]\npythonpath = tests\n")
    probe = repo.path / "tests/test_probe.py"
    original_config = tmp_path / "original-gitconfig"
    original_config.write_text("[user]\n\temail = original@example.com\n")
    probe.write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_case():\n"
        "    Path(os.environ['PARTLET_PROBE_CONFIG']).write_text('[user]\\n')\n"
    )
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(original_config),
        "PARTLET_PROBE_CONFIG": str(original_config),
    }
    proc = subprocess.run(
        ["bash", "scripts/test.sh", str(probe)],
        cwd=gate_project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == pytest.ExitCode.TESTS_FAILED, proc.stdout + proc.stderr
    assert "REPOSITORY TRIPWIRE FIRED" in proc.stdout
    assert NO_EXECUTION not in proc.stderr
    backup = re.search(r"Original contents are backed up in (.+) \(see", proc.stdout)
    assert backup is not None, proc.stdout
    shutil.rmtree(backup[1])
