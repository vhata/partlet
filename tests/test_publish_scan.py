import json

import pytest
from helpers import export_tip

from partlet.gitutil import git
from partlet.manifest import parse_manifest
from partlet.publish import publish_all
from partlet.scan import Scanner, check_gitleaks
from partlet.store import LocalStore

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


def publish(mono, tmp_path, store, approved, gitleaks, description=""):
    m = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
description = "{description}"
""")
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    (result,) = publish_all(mono.path, m, store, work, Scanner(gitleaks, mono.path))
    return result


def test_secret_in_history_blocks_first_publish_before_any_upload(
    mono, tmp_path, gitleaks
):
    mono.write("foo/a.txt", "one\n")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    mono.rm("foo/config.py")
    mono.commit("remove the token again")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")

    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert "secret scan: 1 finding(s): github-pat in config.py:1" in result.reason
    assert FAKE_TOKEN not in result.reason
    assert store.list("s/p/foo/") == []
    assert json.loads(store.get("s/index.json")) == []


def test_secret_in_new_commit_leaves_published_state_alone(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    assert publish(mono, tmp_path, store, approved, gitleaks).status == "published"
    before = {key: store.get(key) for key in store.list("s/")}

    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c2")
    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert {key: store.get(key) for key in store.list("s/")} == before


def test_secret_added_by_a_merge_blocks_the_publish(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    git("checkout", "-q", "-b", "side", cwd=mono.path)
    mono.write("foo/b.txt", "b\n")
    mono.commit("side")
    git("checkout", "-q", "main", cwd=mono.path)
    mono.write("foo/c.txt", "c\n")
    mono.commit("main")
    git("merge", "-q", "--no-ff", "--no-commit", "side", cwd=mono.path)
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("merge side, adding a token")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")

    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert "secret scan: 1 finding(s): github-pat in config.py:1" in result.reason
    assert store.list("s/p/foo/") == []


def test_monorepo_gitleaks_config_is_used(mono, tmp_path, gitleaks):
    mono.write("foo/fixtures/token.txt", FAKE_TOKEN + "\n")
    mono.write(
        ".gitleaks.toml",
        '[extend]\nuseDefault = true\n\n[allowlist]\npaths = ["fixtures/"]\n',
    )
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    assert publish(mono, tmp_path, store, approved, gitleaks).status == "published"


def test_rerender_scans_existing_history_before_writing(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.write(
        ".gitleaks.toml",
        "[extend]\nuseDefault = true\n[allowlist]\npaths = ['config.py']\n",
    )
    mono.commit("allowlisted token")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    assert publish(mono, tmp_path, store, approved, gitleaks).status == "published"
    before = {key: store.get(key) for key in store.list("s/")}
    (mono.path / ".gitleaks.toml").unlink()
    result = publish(mono, tmp_path, store, approved, gitleaks, description="New text")
    assert result.status == "failed"
    assert "secret scan: 1 finding(s)" in result.reason
    assert {key: store.get(key) for key in store.list("s/")} == before


def test_deleted_exported_side_branch_secret_blocks_publication(
    mono, tmp_path, gitleaks
):
    mono.write("foo/a.txt", "base\n")
    mono.commit("base")
    git("checkout", "-q", "-b", "side", cwd=mono.path)
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("secret on side branch")
    mono.rm("foo/config.py")
    mono.commit("delete secret on side branch")
    git("checkout", "-q", "main", cwd=mono.path)
    mono.write("foo/main.txt", "main\n")
    mono.commit("main work")
    git("merge", "-q", "--no-ff", "side", "-m", "merge side", cwd=mono.path)
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert "github-pat in config.py:1" in result.reason
    assert store.list("s/p/foo/") == []
