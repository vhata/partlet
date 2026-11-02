"""Scan an export's full history for secrets with a pinned gitleaks release."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import clean_env

# Must match VERSION in scripts/install-gitleaks.sh (tests/test_scan.py checks).
GITLEAKS_VERSION = "8.30.1"


class ScanError(Exception):
    """gitleaks is missing, is not the pinned version, or failed to run."""


@dataclass(frozen=True)
class Finding:
    rule: str
    commit: str
    file: str
    line: int
    fingerprint: str

    def describe(self) -> str:
        return f"{self.rule} in {self.file}:{self.line} at {self.commit[:12]}"


def find_gitleaks() -> str:
    """The gitleaks beside this Python (a virtualenv's bin), else the one on PATH."""
    beside = Path(sys.executable).parent / "gitleaks"
    if beside.is_file():
        return str(beside)
    found = shutil.which("gitleaks")
    if found is None:
        raise ScanError(
            "gitleaks not found; install it with bash scripts/install-gitleaks.sh"
        )
    return found


def _env() -> dict[str, str]:
    # GITLEAKS_CONFIG and GITLEAKS_CONFIG_TOML would override the monorepo's
    # configuration; partlet always passes it explicitly. The git that gitleaks
    # runs must not read the user's git config either: settings such as
    # diff.noprefix change the paths, and so the fingerprints, it reports.
    env = {k: v for k, v in clean_env().items() if not k.startswith("GITLEAKS_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def check_gitleaks(binary: str | None = None) -> str:
    """Return the path of a gitleaks that is exactly the pinned version."""
    binary = binary or find_gitleaks()
    try:
        proc = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            env=_env(),
            check=False,
        )
    except OSError as e:
        raise ScanError(f"cannot run {binary}: {e}") from e
    version = proc.stdout.strip().removeprefix("v")
    if proc.returncode != 0 or version != GITLEAKS_VERSION:
        raise ScanError(
            f"{binary} reports version {version or '(none)'}; partlet needs gitleaks "
            f"{GITLEAKS_VERSION} exactly (bash scripts/install-gitleaks.sh)"
        )
    return binary


# Diff each merge against its first parent, including octopus merges. This
# controls only the displayed diff: do not add traversal's `--first-parent`,
# because secrets deleted on a side branch before merging must still be scanned.
# Ordinary patches preserve canonical paths for path rules and allowlists.
HISTORY_LOG_OPTS = "--diff-merges=first-parent refs/heads/main"


def _gitleaks(
    repo: Path,
    config_dir: Path,
    workdir: Path,
    binary: str,
    report: Path,
) -> list[dict]:
    cmd = [
        binary,
        "git",
        "--no-banner",
        "--no-color",
        "--redact",
        "--exit-code",
        "0",  # findings come from the report; a non-zero exit is an error
        "--log-level",
        "error",
        "--report-format",
        "json",
        "--report-path",
        str(report),
        "--gitleaks-ignore-path",
        str(config_dir),
        "--log-opts",
        HISTORY_LOG_OPTS,
    ]
    config = config_dir / ".gitleaks.toml"
    if config.is_file():
        cmd += ["--config", str(config)]
    cmd.append(str(repo))
    # A successful invocation must produce its own report. Never reuse an old
    # report if a broken executable exits zero without writing one.
    report.unlink(missing_ok=True)
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True, env=_env(), check=False
        )
    except OSError as e:
        raise ScanError(f"cannot run gitleaks: {e}") from e
    if proc.returncode != 0:
        # Tool errors can echo config values; --redact protects findings only.
        raise ScanError(
            f"gitleaks failed ({proc.returncode}); check the scanner configuration"
        )
    try:
        items = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScanError("cannot read the gitleaks report") from e
    if not isinstance(items, list):
        raise ScanError("cannot read the gitleaks report: not a list")
    return items


def scan_history(
    repo: Path, config_dir: Path, workdir: Path, binary: str
) -> list[Finding]:
    """Scan every commit reachable from refs/heads/main in `repo`, merges included.

    `config_dir` is the monorepo root. Its `.gitleaks.toml`, if present, is the
    gitleaks configuration, and its `.gitleaksignore`, if present, lists accepted
    findings by fingerprint. Secrets are redacted in the report, so a Finding
    never carries one. Needs git 2.31 or newer (first-parent merge diffs).
    """
    repo, config_dir, workdir = repo.resolve(), config_dir.resolve(), workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    items = _gitleaks(repo, config_dir, workdir, binary, workdir / "gitleaks.json")
    findings: dict[str, Finding] = {}
    try:
        for item in items:
            if not isinstance(item, dict) or any(
                not isinstance(item[key], str) or not item[key]
                for key in ("RuleID", "Commit", "File", "Fingerprint")
            ):
                raise ValueError("invalid finding metadata")
            if type(item["StartLine"]) is not int or item["StartLine"] < 1:
                raise ValueError("invalid finding line")
            finding = Finding(
                rule=item["RuleID"],
                commit=item["Commit"],
                file=item["File"],
                line=int(item["StartLine"]),
                fingerprint=item["Fingerprint"],
            )
            # Preserve gitleaks' native fingerprints for .gitleaksignore.
            findings.setdefault(finding.fingerprint, finding)
    except (KeyError, TypeError, ValueError) as e:
        raise ScanError("cannot read the gitleaks report") from e
    return list(findings.values())


@dataclass(frozen=True)
class Scanner:
    """A checked gitleaks binary and the monorepo whose configuration it uses."""

    binary: str
    config_dir: Path

    def scan(self, repo: Path, workdir: Path) -> list[Finding]:
        return scan_history(repo, self.config_dir, workdir, self.binary)
