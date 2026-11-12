"""Exercise the actual Action shell steps using synthetic checkouts and S3."""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from helpers import FAKE_R2_KEY_ID, FAKE_R2_SECRET, Repo, export_tip
from packaging.requirements import Requirement

from partlet.gitutil import git, git_out
from partlet.store import R2Store

ROOT = Path(__file__).resolve().parents[1]
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())
STEPS = ACTION["runs"]["steps"]


def run_step(name, repo, **environment):
    step = next(step for step in STEPS if step.get("name") == name)
    env = dict(os.environ)
    env.update(
        ACTION_PATH=str(ROOT), PY=sys.executable, MANIFEST="partlet.toml", LOCAL_OUT=""
    )
    env.update(environment)
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=repo,
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.fixture
def checkout(tmp_path):
    mono = Repo(tmp_path / "source checkout $(touch injected)")
    mono.write("foo/README.md", "# Foo\n")
    mono.write("private.txt", "Private content stays out of the export.\n")
    mono.commit("Source history")
    tip = export_tip(mono, tmp_path)
    mono.write(
        "partlet.toml",
        '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n'
        f'\n[projects.foo]\npath = "foo"\napproved = "{tip}"\n',
    )
    mono.commit("Committed approval")
    return mono, tip


def test_action_shell_and_supply_chain_contract():
    assert ACTION["runs"]["using"] == "composite"
    for step in STEPS:
        if "run" in step:
            assert step["shell"] == "bash"
            assert step["run"].lstrip().startswith("set -euo pipefail")
            assert "${{" not in step["run"]
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"])
    uv = next(s["with"] for s in STEPS if s.get("uses", "").startswith("astral-sh/"))
    assert uv["version"] == "0.13.5"
    assert len(re.findall(r"'[0-9a-f]{64}'", uv["checksum"])) == 2
    assert uv["enable-cache"] == "false"
    assert uv["working-directory"] == "${{ github.action_path }}"
    installer = (ROOT / "action/install.sh").read_text()
    assert "--require-hashes --no-build" in installer
    assert "--no-config --no-cache" in installer
    for step in STEPS:
        references = str(step)
        if step.get("name") == "Publish":
            for name in (
                "account-id",
                "access-key-id",
                "secret-access-key",
                "bucket",
                "endpoint",
            ):
                assert f"inputs.{name} " in references
        else:
            assert not any(
                f"inputs.{name}" in references
                for name in (
                    "account-id",
                    "access-key-id",
                    "secret-access-key",
                    "bucket",
                    "endpoint",
                )
            )


def test_lock_covers_runtime_dependencies_with_hashes():
    lock = (ROOT / "action/requirements.txt").read_text()
    packages = dict(re.findall(r"^([a-z0-9._-]+)==([^\s]+) \\$", lock, re.MULTILINE))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for requirement in project["project"]["dependencies"]:
        name = re.split(r"[<>=!~\[ ]", requirement, maxsplit=1)[0].lower()
        assert name in packages
        assert packages[name] in Requirement(requirement).specifier
    assert packages["git-filter-repo"] == "2.47.0"
    for block in re.split(r"\n(?=[a-z])", lock[lock.index("boto3==") :]):
        assert "--hash=sha256:" in block
    assert not re.search(r"(^|\n)(-e |--extra-index|--find-links|https?:)", lock)


@pytest.mark.parametrize("branch", ["main", "trunk", "release/public"])
def test_detached_checkout_creates_full_local_branch(checkout, tmp_path, branch):
    mono, _ = checkout
    if branch != "main":
        git("branch", "-m", branch, cwd=mono.path)
        manifest = mono.path / "partlet.toml"
        manifest.write_text(
            manifest.read_text().replace("[site]\n", f'[site]\nbranch = "{branch}"\n')
        )
        mono.commit("Publishing branch")
    clone = tmp_path / "clone"
    git("clone", "-q", str(mono.path), str(clone), cwd=tmp_path)
    git("checkout", "--detach", f"origin/{branch}", cwd=clone)
    git("branch", "-D", branch, cwd=clone)
    result = run_step("Prepare publishing checkout", clone)
    assert result.returncode == 0, result.stderr
    assert git_out("rev-parse", f"refs/heads/{branch}", cwd=clone) == git_out(
        "rev-parse", "HEAD", cwd=clone
    )


def test_missing_branch_and_shallow_checkout_fail(checkout, tmp_path):
    mono, _ = checkout
    clone = tmp_path / "shallow"
    git("clone", "-q", "--depth", "1", mono.path.as_uri(), str(clone), cwd=tmp_path)
    result = run_step("Prepare publishing checkout", clone)
    assert result.returncode == 2 and "fetch-depth: 0" in result.stderr
    git("checkout", "--detach", cwd=mono.path)
    git("branch", "-D", "main", cwd=mono.path)
    result = run_step("Prepare publishing checkout", mono.path)
    assert result.returncode == 2 and "neither refs/heads/main" in result.stderr


def test_other_branch_and_uncommitted_approval_fail(checkout, tmp_path):
    mono, _ = checkout
    mono.write(
        "partlet.toml", (mono.path / "partlet.toml").read_text() + "# Uncommitted\n"
    )
    result = run_step("Prepare publishing checkout", mono.path)
    assert (
        result.returncode == 2 and "differs from the version committed" in result.stderr
    )
    # Local smoke mode must not accidentally bypass the real publishing gate.
    result = run_step("Publish", mono.path, LOCAL_OUT=str(tmp_path / "out"))
    assert result.returncode == 2 and not (tmp_path / "out").exists()
    git("checkout", "--", "partlet.toml", cwd=mono.path)
    git("checkout", "-b", "feature", cwd=mono.path)
    mono.write("private.txt", "Unrelated feature change\n")
    mono.commit("Feature")
    result = run_step("Prepare publishing checkout", mono.path)
    assert result.returncode == 2 and "checkout of the tip of main" in result.stderr


@pytest.mark.parametrize("local", [True, False])
def test_actual_publish_step_isolated_and_approved(
    checkout, tmp_path, r2_config, local
):
    mono, tip = checkout
    hostile = "raise RuntimeError('private code imported')\n"
    for name in ("partlet.py", "jinja2.py", "git_filter_repo.py", "sitecustomize.py"):
        mono.write(name, hostile)
    mono.commit("Private shadow modules")
    environment = {
        "PYTHONPATH": str(mono.path),
        "PYTHONHOME": str(mono.path),
        "PARTLET_R2_ENDPOINT": r2_config.endpoint_url,
        "PARTLET_R2_BUCKET": r2_config.bucket,
        "PARTLET_R2_ACCESS_KEY_ID": FAKE_R2_KEY_ID,
        "PARTLET_R2_SECRET_ACCESS_KEY": FAKE_R2_SECRET,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    if local:
        environment["LOCAL_OUT"] = str(tmp_path / "out")
    prepared = run_step(
        "Prepare publishing checkout", mono.path, PYTHONPATH=str(mono.path)
    )
    assert prepared.returncode == 0, prepared.stderr
    result = run_step("Publish", mono.path, **environment)
    assert result.returncode == 0, result.stdout + result.stderr
    if local:
        current = (tmp_path / "out/s/p/foo/current").read_bytes()
    else:
        current = R2Store(r2_config).get("s/p/foo/current")
    assert json.loads(current)["tip"] == tip
    assert "published" in result.stdout
    assert "gitleaks" in (tmp_path / "summary").read_text()
    assert (
        FAKE_R2_SECRET
        not in result.stdout + result.stderr + (tmp_path / "summary").read_text()
    )
    assert not (mono.path / "injected").exists()


def test_consumer_workflow_serializes_publications_and_removes_checkout_credentials():
    # BaseLoader keeps the YAML 1.2 'on' key rather than treating it as bool.
    workflow = yaml.load(
        (ROOT / "examples/partlet.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "pull_request" not in workflow["on"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert workflow["concurrency"]["group"] == "partlet-SOURCE"
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["publish"]
    assert job["runs-on"] == "ubuntu-24.04"
    checkout = job["steps"][0]
    assert checkout["with"] == {"fetch-depth": "0", "persist-credentials": "false"}
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert "@PARTLET_RELEASE_SHA" in job["steps"][1]["uses"]


def configure_custom_theme(mono):
    mono.write(
        "themes/custom/theme.toml",
        'id = "custom"\nname = "Custom theme"\nversion = "1.0"\n'
        'format_version = 2\nmodes = ["auto", "light", "dark"]\n'
        'license = "MIT"\nassets = []\n',
    )
    mono.write("themes/custom/style.css", ":root { --link: #123456; }\n")
    mono.write("themes/custom/LICENSE", "Example license provenance\n")
    path = mono.path / "partlet.toml"
    path.write_text(
        path.read_text() + '\n[site.theme]\npath = "themes/custom"\nmode = "dark"\n'
    )
    mono.commit("vendored theme")


@pytest.mark.parametrize("local", [True, False])
def test_actual_action_publishes_committed_custom_theme(
    checkout, tmp_path, r2_config, local
):
    mono, tip = checkout
    configure_custom_theme(mono)
    environment = {
        "PARTLET_R2_ENDPOINT": r2_config.endpoint_url,
        "PARTLET_R2_BUCKET": r2_config.bucket,
        "PARTLET_R2_ACCESS_KEY_ID": FAKE_R2_KEY_ID,
        "PARTLET_R2_SECRET_ACCESS_KEY": FAKE_R2_SECRET,
    }
    if local:
        environment["LOCAL_OUT"] = str(tmp_path / "out")
    result = run_step("Publish", mono.path, **environment)
    assert result.returncode == 0, result.stdout + result.stderr
    if local:
        from partlet.store import LocalStore

        store = LocalStore(tmp_path / "out")
    else:
        store = R2Store(r2_config)
    record = json.loads(store.get("s/site-theme.json"))
    assert record["name"] == "custom" and record["mode"] == "dark"
    assert b"#123456" in store.get(f"s/static/themes/{record['digest']}/style.css")
    current = json.loads(store.get("s/p/foo/current"))
    assert current["tip"] == tip
    assert record["digest"].encode() in store.get(
        f"s/p/foo/site/{current['build']}/index.html"
    )


@pytest.mark.parametrize("local", [True, False])
def test_actual_action_rejects_dirty_custom_theme_before_writes(
    checkout, tmp_path, r2_config, local
):
    mono, _ = checkout
    configure_custom_theme(mono)
    mono.write("themes/custom/style.css", ":root { --link: #654321; }\n")
    environment = {
        "PARTLET_R2_ENDPOINT": r2_config.endpoint_url,
        "PARTLET_R2_BUCKET": r2_config.bucket,
        "PARTLET_R2_ACCESS_KEY_ID": FAKE_R2_KEY_ID,
        "PARTLET_R2_SECRET_ACCESS_KEY": FAKE_R2_SECRET,
    }
    if local:
        environment["LOCAL_OUT"] = str(tmp_path / "out")
    prepare = run_step("Prepare publishing checkout", mono.path)
    assert prepare.returncode == 2
    assert "differs" in prepare.stderr
    result = run_step("Publish", mono.path, **environment)
    assert result.returncode == 2
    assert "differs" in result.stderr
    assert R2Store(r2_config).list("s/") == []
    assert not (tmp_path / "out").exists()
