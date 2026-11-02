import json
import re
from pathlib import Path

import pytest

from partlet.gitutil import GitError, git
from partlet.scan import (
    GITLEAKS_VERSION,
    ScanError,
    Scanner,
    check_gitleaks,
    scan_history,
)

ROOT = Path(__file__).resolve().parent.parent

# Built at run time so this file holds no string that looks like a token.
FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


def scan(mono, tmp_path, gitleaks):
    return Scanner(gitleaks, mono.path).scan(mono.path, tmp_path / "scan")


def test_pinned_version_matches_installer():
    script = (ROOT / "scripts" / "install-gitleaks.sh").read_text()
    assert (
        re.search(r"^VERSION=(\S+)$", script, re.MULTILINE).group(1) == GITLEAKS_VERSION
    )


def test_clean_history_has_no_findings(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "nothing to see\n")
    mono.commit("c1")
    assert scan(mono, tmp_path, gitleaks) == []


def test_secret_in_a_deleted_file_is_found(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    leaky = mono.commit("add token")
    mono.rm("foo/config.py")
    mono.commit("remove token")
    findings = scan(mono, tmp_path, gitleaks)
    assert [(f.rule, f.file, f.commit, f.line) for f in findings] == [
        ("github-pat", "foo/config.py", leaky, 1)
    ]
    assert FAKE_TOKEN not in findings[0].describe()


def branch(mono, name, start="main"):
    git("checkout", "-q", "-b", name, start, cwd=mono.path)


def checkout(mono, name):
    git("checkout", "-q", name, cwd=mono.path)


def test_secret_added_by_a_merge_is_found(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    branch(mono, "side")
    mono.write("foo/b.txt", "b\n")
    mono.commit("side")
    checkout(mono, "main")
    mono.write("foo/c.txt", "c\n")
    mono.commit("main")
    git("merge", "-q", "--no-ff", "--no-commit", "side", cwd=mono.path)
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    merge = mono.commit("merge side, adding a token")
    findings = scan(mono, tmp_path, gitleaks)
    assert [(f.file, f.commit) for f in findings] == [("foo/config.py", merge)]


def conflict_resolution(mono):
    mono.write("foo/a.txt", "base\n")
    mono.commit("c1")
    branch(mono, "side")
    mono.write("foo/a.txt", "side\n")
    mono.commit("side")
    checkout(mono, "main")
    mono.write("foo/a.txt", "main\n")
    mono.commit("main")
    with pytest.raises(GitError):
        git("merge", "-q", "side", cwd=mono.path)  # conflicts
    mono.write("foo/a.txt", f'resolved = "{FAKE_TOKEN}"\n')
    return mono.commit("resolve the conflict")


def test_secret_in_a_conflict_resolution_is_found(mono, tmp_path, gitleaks):
    merge = conflict_resolution(mono)
    (finding,) = scan(mono, tmp_path, gitleaks)
    assert (finding.commit, finding.file) == (merge, "foo/a.txt")


@pytest.mark.parametrize(
    "config, expected",
    [
        (
            (
                "[[rules]]\nid = 'path-token'\n"
                "regex = '''ghp_[0-9A-Za-z]{36}'''\n"
                "path = '''^foo/a[.]txt$'''\n"
            ),
            ["path-token"],
        ),
        (
            "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''^b/''']\n",
            ["github-pat"],
        ),
        (
            "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''^foo/''']\n",
            [],
        ),
    ],
    ids=["path-rule", "unrelated-path-allowlist", "matching-path-allowlist"],
)
def test_conflict_resolution_uses_canonical_paths_for_config(
    mono, tmp_path, gitleaks, config, expected
):
    merge = conflict_resolution(mono)
    mono.write(".gitleaks.toml", config)
    findings = scan(mono, tmp_path, gitleaks)
    assert [f.rule for f in findings] == expected
    assert all((f.commit, f.file) == (merge, "foo/a.txt") for f in findings)


def test_merged_branch_findings_keep_native_fingerprints(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    branch(mono, "side")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    leaky = mono.commit("side adds a token")
    checkout(mono, "main")
    mono.write("foo/c.txt", "c\n")
    mono.commit("main")
    git("merge", "-q", "--no-ff", "side", "-m", "merge side", cwd=mono.path)
    merge = git("rev-parse", "HEAD", cwd=mono.path).stdout.decode().strip()
    checkout(mono, "side")
    mono.write("foo/d.txt", "d\n")
    mono.commit("side continues")
    checkout(mono, "main")
    git("merge", "-q", "--no-ff", "side", "-m", "merge again", cwd=mono.path)
    findings = scan(mono, tmp_path, gitleaks)
    assert {(f.file, f.commit) for f in findings} == {
        ("foo/config.py", leaky),
        ("foo/config.py", merge),
    }
    # The origin and importing merge are distinct accepted occurrences.
    origin = next(f for f in findings if f.commit == leaky)
    ignore = mono.path / ".gitleaksignore"
    ignore.write_text(origin.fingerprint + "\n")
    assert [f.commit for f in scan(mono, tmp_path / "origin-ignored", gitleaks)] == [
        merge
    ]
    ignore.write_text("\n".join(f.fingerprint for f in findings) + "\n")
    assert scan(mono, tmp_path / "all-ignored", gitleaks) == []


def test_deleted_side_branch_secret_is_scanned(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    branch(mono, "side")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    leaky = mono.commit("side adds a token")
    mono.rm("foo/config.py")
    mono.commit("side removes the token")
    checkout(mono, "main")
    mono.write("foo/c.txt", "c\n")
    mono.commit("main")
    git("merge", "-q", "--no-ff", "side", "-m", "merge side", cwd=mono.path)
    findings = scan(mono, tmp_path, gitleaks)
    assert [(f.file, f.commit) for f in findings] == [("foo/config.py", leaky)]


def test_secret_added_by_an_octopus_merge_is_found_once(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    for name in ("one", "two"):
        branch(mono, name, "main")
        mono.write(f"foo/{name}.txt", f"{name}\n")
        mono.commit(name)
    checkout(mono, "main")
    mono.write("foo/c.txt", "c\n")
    mono.commit("main")
    git("merge", "-q", "--no-commit", "one", "two", cwd=mono.path)
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    merge = mono.commit("octopus, adding a token")
    findings = scan(mono, tmp_path, gitleaks)
    assert [(f.file, f.commit) for f in findings] == [("foo/config.py", merge)]


def test_users_git_config_does_not_change_reported_paths(
    mono, tmp_path, gitleaks, monkeypatch
):
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[diff]\n\tnoprefix = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    mono.write("a/x.txt", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    assert [f.file for f in scan(mono, tmp_path, gitleaks)] == ["a/x.txt"]


@pytest.mark.parametrize(
    "name", ["foo/a b.txt", "foo/é.txt", 'foo/a"b.txt', "foo/a\tb.txt"]
)
def test_git_quoted_names_keep_canonical_paths(mono, tmp_path, gitleaks, name):
    mono.write(name, FAKE_TOKEN + "\n")
    mono.commit("secret in a Git-quoted path")
    (finding,) = scan(mono, tmp_path, gitleaks)
    assert finding.file == name


def test_report_is_redacted(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("add token")
    scan(mono, tmp_path, gitleaks)
    report = (tmp_path / "scan" / "gitleaks.json").read_text()
    assert FAKE_TOKEN not in report
    assert json.loads(report)[0]["Secret"] == "REDACTED"


def test_monorepo_config_allowlists_paths(mono, tmp_path, gitleaks):
    mono.write("foo/fixtures/token.txt", FAKE_TOKEN + "\n")
    mono.write(
        ".gitleaks.toml",
        '[extend]\nuseDefault = true\n\n[allowlist]\npaths = ["fixtures/"]\n',
    )
    mono.commit("c1")
    assert scan(mono, tmp_path, gitleaks) == []


def test_monorepo_config_can_extend_a_relative_rules_file(mono, tmp_path, gitleaks):
    mono.write("foo/token.txt", FAKE_TOKEN + "\n")
    mono.write(".gitleaks.toml", "[extend]\npath = 'rules/shared.toml'\n")
    mono.write(
        "rules/shared.toml",
        "[[rules]]\nid = 'shared-token'\n"
        "regex = '''ghp_[0-9A-Za-z]{36}'''\n"
        "path = '''^foo/token[.]txt$'''\n",
    )
    mono.commit("token and configured rules")
    (finding,) = scan(mono, tmp_path, gitleaks)
    assert (finding.rule, finding.file) == ("shared-token", "foo/token.txt")


def test_inherited_gitleaks_config_cannot_override_monorepo_rules(
    mono, tmp_path, gitleaks, monkeypatch
):
    mono.write("foo/token.txt", FAKE_TOKEN + "\n")
    mono.commit("token")
    bogus = tmp_path / "bogus.toml"
    bogus.write_text("not a valid config")
    monkeypatch.setenv("GITLEAKS_CONFIG", str(bogus))
    monkeypatch.setenv("GITLEAKS_CONFIG_TOML", "also not a valid config")
    (finding,) = scan(mono, tmp_path, gitleaks)
    assert finding.rule == "github-pat"


def test_gitleaksignore_accepts_a_fingerprint(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    (finding,) = scan(mono, tmp_path, gitleaks)
    (mono.path / ".gitleaksignore").write_text(finding.fingerprint + "\n")
    assert scan(mono, tmp_path / "again", gitleaks) == []


def test_wrong_version_is_refused(tmp_path):
    fake = tmp_path / "gitleaks"
    fake.write_text("#!/bin/sh\necho 8.0.0\n")
    fake.chmod(0o755)
    with pytest.raises(ScanError, match=f"needs gitleaks {GITLEAKS_VERSION}"):
        check_gitleaks(str(fake))


def test_gitleaks_failure_is_an_error(tmp_path, gitleaks):
    with pytest.raises(ScanError, match="gitleaks failed"):
        scan_history(tmp_path / "missing.git", tmp_path, tmp_path / "scan", gitleaks)


def test_missing_binary_is_a_scan_error(tmp_path):
    with pytest.raises(ScanError, match="cannot run gitleaks"):
        scan_history(tmp_path, tmp_path, tmp_path / "scan", str(tmp_path / "missing"))


def test_success_without_report_cannot_reuse_an_old_clean_report(tmp_path):
    work = tmp_path / "scan"
    work.mkdir()
    (work / "gitleaks.json").write_text("[]")
    fake = tmp_path / "gitleaks"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    with pytest.raises(ScanError, match="cannot read the gitleaks report"):
        scan_history(tmp_path, tmp_path, work, str(fake))


def test_error_output_does_not_expose_config_or_secrets(tmp_path):
    fake = tmp_path / "gitleaks"
    fake.write_text(f"#!/bin/sh\necho '{FAKE_TOKEN}' >&2\nexit 1\n")
    fake.chmod(0o755)
    with pytest.raises(ScanError) as error:
        scan_history(tmp_path, tmp_path, tmp_path / "scan", str(fake))
    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.parametrize("payload", ["null", "{}", "[null]", '[{"RuleID": null}]'])
def test_malformed_report_fails_closed(tmp_path, monkeypatch, payload):
    from subprocess import CompletedProcess

    from partlet import scan as scanner

    def run(cmd, **kwargs):
        Path(cmd[cmd.index("--report-path") + 1]).write_text(payload)
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scanner.subprocess, "run", run)
    with pytest.raises(ScanError, match="cannot read the gitleaks report"):
        scan_history(tmp_path, tmp_path, tmp_path / "scan", "gitleaks")
