#!/usr/bin/env bash
set -euo pipefail

# Shape a bundled source checkout into the tree that `main` carries.
#
# `main` is `develop` with the skill bundles materialized (scripts/bundle/bundle.sh),
# versions stamped (scripts/release/sync-version.mjs), skill requirements pinned
# (scripts/release/pin-cadgen-requirements.sh), and ONLY `models/` removed. Nothing
# else is trimmed: apps/, packages/, tests/ and requirements-dev.txt ship, so the
# source behind every release is discoverable on the default branch. That tree is
# ~15 MB with no LFS objects; models/ is the fixture corpus and the only thing
# whose absence buys anything.
#
# This script does the two things the bundle does not:
#
#   1. removes the roots in REMOVED_ROOTS (models/);
#   2. dereferences the development symlinks that are NOT bundle outputs. The
#      bundle replaces skills/cad-viewer/scripts/viewer with the built runtime,
#      but apps/viewer/packages/cadgen-js stays a symlink into packages/ -- and a
#      symlink must never reach the published tree (Codex `plugin add` drops them
#      silently; see scripts/github-workflows/check-builds.sh). It becomes a real
#      copy of the package source, exactly as the cad-viewer mirror ships it.
#
# It is a PUBLISH-TREE transformation, run by the Release workflow after bundle.sh
# --clean and every check, before pin-cadgen-requirements.sh and the publish commit.
# It never runs on a development checkout: it deletes models/ and breaks the
# symlink layout. scripts/github-workflows/check-publish-tree.sh verifies the result.
#
# Usage:
#   scripts/release/prepare-publish-tree.sh
#   scripts/release/prepare-publish-tree.sh --print-removed-roots
#   scripts/release/prepare-publish-tree.sh --print-dereferenced-links

REPO_ROOT="${PUBLISH_TREE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# The single source of truth for what the publish tree drops. The Release
# workflow reads it (--print-removed-roots) to assert the roots are absent from
# the publish commit and to stop demanding generated outputs under them.
REMOVED_ROOTS=(models)

# Development symlinks that survive the bundle and are dereferenced here. Every
# link scripts/dev/setup-symlinks.sh creates must be either a bundle output
# (scripts/bundle/bundle-skill.sh --all --print-outputs) or listed here;
# tests/python/global/test_publish_tree.py holds that.
DEREFERENCED_LINKS=(apps/viewer/packages/cadgen-js)

# What a dereferenced copy leaves behind: installed and generated state that is
# never committed. Matches scripts/viewer/sync-cad-viewer-repo.sh, which ships the
# same copy to the standalone mirror.
COPY_EXCLUDES=(
  --exclude node_modules
  --exclude dist
  --exclude dist-verify
  --exclude .vite
  --exclude coverage
  --exclude tmp
  --exclude .venv
  --exclude .pytest_cache
  --exclude __pycache__
  --exclude '*.pyc'
  --exclude '*.pyo'
  --exclude '*.egg-info'
  --exclude .DS_Store
)

usage() {
  cat <<'EOF'
Usage:
  scripts/release/prepare-publish-tree.sh
  scripts/release/prepare-publish-tree.sh --print-removed-roots
  scripts/release/prepare-publish-tree.sh --print-dereferenced-links

Turns a bundled checkout into the publish tree: removes models/ and replaces the
development symlinks the bundle leaves in place with real copies. Run only in the
Release workflow (or a scratch worktree) -- never on a development checkout.
EOF
}

case "${1:-}" in
  "") ;;
  --print-removed-roots)
    printf '%s\n' "${REMOVED_ROOTS[@]}"
    exit 0
    ;;
  --print-dereferenced-links)
    printf '%s\n' "${DEREFERENCED_LINKS[@]}"
    exit 0
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac

cd "$REPO_ROOT"

for root in "${REMOVED_ROOTS[@]}"; do
  rm -rf "$root"
  if [ -e "$root" ] || [ -L "$root" ]; then
    echo "Failed to remove $root from the publish tree." >&2
    exit 1
  fi
  echo "Removed $root/"
done

command -v rsync >/dev/null 2>&1 || {
  echo "rsync is required to dereference development symlinks." >&2
  exit 1
}

for link in "${DEREFERENCED_LINKS[@]}"; do
  if [ ! -L "$link" ]; then
    if [ -d "$link" ]; then
      echo "Already a real directory: $link"
      continue
    fi
    echo "Expected a development symlink at $link; found nothing." >&2
    echo "Run scripts/dev/setup-symlinks.sh --check on the source checkout." >&2
    exit 1
  fi
  link_value="$(readlink "$link")"
  target="$(cd "$(dirname "$link")" && cd "$link_value" 2>/dev/null && pwd -P || true)"
  if [ -z "$target" ] || [ ! -d "$target" ]; then
    echo "Development symlink $link points at a missing directory: $link_value" >&2
    exit 1
  fi
  rm "$link"
  mkdir -p "$link"
  # --copy-links so a symlink INSIDE the target lands as a file too: the copy
  # must contain no symlink at any depth.
  rsync -a --copy-links "${COPY_EXCLUDES[@]}" "$target/" "$link/"
  if [ ! -f "$link/package.json" ] && [ ! -f "$link/pyproject.toml" ]; then
    echo "Dereferenced copy at $link carries no package manifest; refusing to ship it." >&2
    exit 1
  fi
  echo "Dereferenced $link -> ${target#"$REPO_ROOT"/}"
done

echo "Publish tree prepared: removed ${REMOVED_ROOTS[*]}; dereferenced ${DEREFERENCED_LINKS[*]}."
