#!/usr/bin/env bash
set -euo pipefail

# Rewrite every `--editable <path>/packages/cadgen` requirement to
# `cadgen==<VERSION>` so published skills resolve cadgen from PyPI.
#
# A source checkout installs cadgen editable through the development symlinks,
# which only resolves because `packages/cadgen` sits beside the skill. An
# installed skill has no such sibling, so the published tree must name the PyPI
# release instead. The vendored package copy stays in the bundle as an offline
# fallback (`pip install ./<path>/packages/cadgen`).
#
# This is a PUBLISH-TREE transformation, run by the Release workflow between
# `bundle.sh --clean` and the publish commit — the same place `models/` is
# removed. It deliberately does NOT live in bundle.sh: that also runs `--check`
# against a development checkout, where rewriting the checked-in requirements
# would dirty the source tree and break the freshness check.
#
# Before the plugin package moved to the repo root, this ran inside
# bundle-plugin.sh over the generated `plugins/cad/skills` copy. There is no
# copy any more — `skills/` is what ships — so it runs over the tree in place.
#
# Usage: scripts/release/pin-cadgen-requirements.sh [--check]
#   --check  report what would change and exit 1 if anything would, without writing.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=1
elif [ -n "${1:-}" ]; then
  echo "usage: scripts/release/pin-cadgen-requirements.sh [--check]" >&2
  exit 2
fi

version="$(tr -d '[:space:]' < VERSION)"
if [ -z "$version" ]; then
  echo "Missing canonical release version: VERSION" >&2
  exit 1
fi

# A skill that no longer vendors cadgen names the DISTRIBUTION instead, optionally with
# extras (`cadgen[snapshot]`). Unpinned on develop so the editable install from
# requirements-dev.txt satisfies it; pinned here so a published skill resolves the exact
# release from PyPI.
DIST_RE='^cadgen(\[[a-z0-9_,-]+\])?[[:space:]]*$'

pending=0
while IFS= read -r manifest; do
  if ! grep -Eq "$DIST_RE" "$manifest"; then
    continue
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "would pin: $manifest -> cadgen==$version"
    pending=1
    continue
  fi
  sed -E -i.bak -e "s|$DIST_RE|cadgen\1==$version|" "$manifest"
  rm -f "$manifest.bak"
  echo "pinned: $manifest -> cadgen==$version"
done < <(
  find . \
    \( -name node_modules -o -name .git -o -name .venv -o -name tmp -o -name models \) -prune -o \
    -name requirements.txt -type f -print | sort
)

if [ "$CHECK_ONLY" -eq 1 ] && [ "$pending" -ne 0 ]; then
  echo "Unpinned cadgen requirements remain." >&2
  exit 1
fi
