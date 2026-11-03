#!/usr/bin/env bash
# Format tracked Markdown, excluding vendored Docket files. --check never
# rewrites; --staged formats commit candidates without changing the index.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:---write}"
if [ "$#" -gt 1 ] || { [ "$mode" != --write ] && [ "$mode" != --check ] && [ "$mode" != --staged ]; }; then
  echo "usage: bash scripts/fmt-markdown.sh [--write|--check|--staged]" >&2
  exit 2
fi
[ -x .venv/bin/mdformat ] || { echo "fmt-markdown: run bash scripts/setup.sh first" >&2; exit 1; }

list_files() {
  if [ "$mode" = --staged ]; then
    git diff --cached --name-only --diff-filter=ACMR -z
  else
    git ls-files -z
  fi
}

format() {
  # Docket parses queue metadata and preserves settings one line at a
  # time. Joining prose keeps bold outcomes and settings on single lines.
  case "$file" in
    AGENTS.md|TODO.md|review/BACKLOG.md) .venv/bin/mdformat --wrap no "$@" ;;
    *) .venv/bin/mdformat "$@" ;;
  esac
}

list_files | (
  status=0
  while IFS= read -r -d '' file; do
    case "$file" in
      docket/*) continue ;;
      *.[mM][dD]|*.[mM][aA][rR][kK][dD][oO][wW][nN]) ;;
      *) continue ;;
    esac

    if [ "$mode" = --staged ]; then
      # Symlinks are not Markdown documents. Check the index mode rather
      # than the working copy, which might have unstaged type changes.
      case "$(git ls-files --stage -- "$file")" in
        100*) ;;
        *) continue ;;
      esac
      if git show ":$file" | format --check -; then
        continue
      fi
      if git diff --quiet -- "$file" && [ -f "$file" ] && [ ! -L "$file" ]; then
        format "./$file"
        echo "fmt-markdown: formatted $file; review and stage it again" >&2
      else
        echo "fmt-markdown: $file has unformatted staged content and unstaged changes; format and restage your selected changes" >&2
      fi
      status=1
    elif [ -f "$file" ] && [ ! -L "$file" ]; then
      if [ "$mode" = --check ]; then
        format --check "./$file" || status=1
      else
        format "./$file"
      fi
    fi
  done
  exit "$status"
)
