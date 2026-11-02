#!/usr/bin/env bash
# Install the pinned gitleaks release into DEST (default: this worktree's
# .venv/bin) after checking the download against the SHA-256 recorded here.
# scripts/setup.sh and action.yml both call it, so development, CI and the
# action run the same build. Partlet's scan.py refuses any other version.
# To bump: change VERSION and the four hashes, taken from the release's
# gitleaks_<VERSION>_checksums.txt, together with GITLEAKS_VERSION in
# src/partlet/scan.py, in a PR of its own.
set -euo pipefail

VERSION=8.30.1
dest=${1:-"$(cd "$(dirname "$0")/.." && pwd)/.venv/bin"}

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux_x64 sha256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
  Linux-aarch64 | Linux-arm64) platform=linux_arm64 sha256=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
  Darwin-x86_64) platform=darwin_x64 sha256=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
  Darwin-arm64) platform=darwin_arm64 sha256=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
  *) echo "install-gitleaks: no pinned build for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac

if [ -x "$dest/gitleaks" ] && [ "$("$dest/gitleaks" version 2>/dev/null)" = "$VERSION" ]; then
  echo "install-gitleaks: gitleaks $VERSION already in $dest"
  exit 0
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
archive="gitleaks_${VERSION}_${platform}.tar.gz"
curl -fsSL --retry 3 -o "$tmp/$archive" \
  "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${archive}"
if command -v sha256sum >/dev/null; then
  actual=$(sha256sum "$tmp/$archive" | cut -d' ' -f1)
else
  actual=$(shasum -a 256 "$tmp/$archive" | cut -d' ' -f1)
fi
if [ "$actual" != "$sha256" ]; then
  echo "install-gitleaks: checksum mismatch for $archive: expected $sha256, got $actual" >&2
  exit 1
fi
mkdir "$tmp/unpacked"
tar -xzf "$tmp/$archive" -C "$tmp/unpacked" gitleaks
mkdir -p "$dest"
install -m 0755 "$tmp/unpacked/gitleaks" "$dest/gitleaks"
echo "install-gitleaks: installed gitleaks $VERSION in $dest"
