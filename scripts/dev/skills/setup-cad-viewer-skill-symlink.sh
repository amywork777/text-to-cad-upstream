#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
UTILS_SCRIPT="$REPO_ROOT/scripts/dev/symlink-utils.sh"

MODE="write"

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/setup-skill-symlink.sh cad-viewer [--check]

Sets up CAD Viewer development symlinks.

Options:
  --check     Verify symlinks are intact without changing files.
  -h, --help  Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check)
      MODE="check"
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
  shift
done

# shellcheck source=scripts/dev/symlink-utils.sh
source "$UTILS_SCRIPT"

check_no_tracked_viewer_dist() {
  # The built client belongs in cadgen's packaged runtime, which ships in the wheel. A
  # tracked copy would be a second, silently divergent one -- and a 16 MB Vite output
  # re-committed on every client change.
  local tracked_dist
  tracked_dist="$(
    git ls-files \
      "packages/cadgen/src/cadgen/_runtime/viewer" \
      "packages/cadgen/src/cadgen/_runtime/viewer/**" \
      2>/dev/null || true
  )"

  if [ -n "$tracked_dist" ]; then
    echo "packages/cadgen/src/cadgen/_runtime/viewer must not be tracked: it is a build" >&2
    echo "output that CI and the publish job regenerate before building the wheel." >&2
    echo "$tracked_dist" | sed 's/^/- /' >&2
    return 1
  fi
}

cd "$REPO_ROOT"
setup_link "$MODE" "viewer/packages/cadjs" "../../packages/cadjs"
if [ "$MODE" = "check" ]; then
  check_no_tracked_viewer_dist
fi
