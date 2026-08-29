#!/usr/bin/env bash
set -euo pipefail

# Bundle the self-contained CAD Viewer runtime into the cad-viewer skill
# (skills/cad-viewer/scripts/viewer).
#
# The viewer is a standalone app: cadgen does not ship or launch it. What the
# skill needs is exactly what a wheel used to carry — the built SPA plus the
# dependency-free JS server — laid out so
#   node scripts/viewer/server/main.mjs --root <abs>
# works with NO install step (the client is prebuilt, the server has zero npm
# dependencies; Node >= 22 is the one requirement, which cadgen already has).
#
# On develop, skills/cad-viewer/scripts/viewer is a SYMLINK to viewer/ (the dev
# layout, managed by scripts/dev/setup-symlinks.sh); this bundler replaces it
# with the real runtime for CI and the publish tree, where a symlink must never
# survive (installer semantics: Codex silently drops symlinks — see
# check-builds.sh).
#
# The WASM STEP-import kernel (opencascade.js) IS shipped: exactly four files
# vendored at node_modules/opencascade.js/ inside the runtime — the path
# server/import/ocKernel.mjs already resolves — so the installed skill imports
# raw STEPs with no Python and no npm install. The vendored version must match
# the viewer's committed lockfile pin (the parity suites fence that version);
# the bundle fails on a mismatch. node_modules is otherwise still not shipped.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODE="write"
BUILD=1
CLEAN=0
PRINT_OUTPUTS=0

VIEWER_DIR="$REPO_ROOT/viewer"
RUNTIME_DIR="$REPO_ROOT/skills/cad-viewer/scripts/viewer"
CHECK_DIR="${CAD_VIEWER_RUNTIME_CHECK_DIR:-$REPO_ROOT/tmp/cad-viewer-runtime-check}"
VIEWER_PACKAGE_MANAGER="${CAD_VIEWER_PACKAGE_MANAGER:-}"
RELEASE_VERSION="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"

usage() {
  cat <<'EOF'
Usage:
  scripts/bundle/bundle-skill.sh cad-viewer [--check] [--clean] [--no-build]

Bundles the self-contained CAD Viewer runtime (built client + JS server) used
by skills/cad-viewer. Client sourcemaps are included so installed skill
runtimes can be debugged from browser DevTools.

Options:
  --check     Bundle into tmp/ and fail if skills/cad-viewer/scripts/viewer is
              stale. Skipped while the path is a development symlink.
  --clean     Remove temporary check directories first.
  --no-build  Reuse the current viewer/dist instead of rebuilding the viewer.
              The existing dist must already include client sourcemaps.
  --print-outputs
              Print the repo-relative generated output paths, then exit.
  -h, --help  Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --clean) CLEAN=1 ;;
    --no-build) BUILD=0 ;;
    --print-outputs) PRINT_OUTPUTS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$PRINT_OUTPUTS" -eq 1 ]; then
  printf '%s\n' "${RUNTIME_DIR#"$REPO_ROOT"/}"
  exit 0
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required to build the CAD Viewer runtime." >&2
    exit 1
  fi
}

# The COMMITTED lockfile decides, not what happens to be installed on this machine:
# pnpm and npm lay out node_modules differently, so the same source revision could
# otherwise be bundled against a different tree. An explicit
# CAD_VIEWER_PACKAGE_MANAGER still wins.
resolve_viewer_package_manager() {
  if [ -n "${VIEWER_PACKAGE_MANAGER:-}" ]; then
    echo "$VIEWER_PACKAGE_MANAGER"
    return
  fi
  if [ -f "$VIEWER_DIR/package-lock.json" ]; then
    echo "npm"
    return
  fi
  if [ -f "$VIEWER_DIR/pnpm-lock.yaml" ]; then
    echo "pnpm"
    return
  fi
  if command -v pnpm >/dev/null 2>&1; then
    echo "pnpm"
    return
  fi
  echo "npm"
}

run_viewer_build() {
  local package_manager
  package_manager="$(resolve_viewer_package_manager)"
  require_command "$package_manager"
  # Sourcemaps ship on purpose: an installed runtime is debuggable from DevTools.
  case "$package_manager" in
    pnpm) CI=true pnpm --dir "$VIEWER_DIR" run build --sourcemap true ;;
    npm)  npm --prefix "$VIEWER_DIR" run build -- --sourcemap true ;;
    *)
      echo "Unsupported CAD Viewer package manager: $package_manager" >&2
      echo "Set CAD_VIEWER_PACKAGE_MANAGER to pnpm or npm." >&2
      exit 1
      ;;
  esac
}

require_client_sourcemaps() {
  local dist_dir="$1"
  local map_count
  if [ ! -d "$dist_dir/assets" ]; then
    echo "Missing Viewer dist assets directory: $dist_dir/assets" >&2
    exit 1
  fi
  map_count="$(find "$dist_dir/assets" -type f -name '*.map' | wc -l | tr -d '[:space:]')"
  if [ "$map_count" -eq 0 ]; then
    echo "Missing Viewer client sourcemaps in $dist_dir/assets." >&2
    echo "Run scripts/bundle/bundle-skill.sh cad-viewer without --no-build to regenerate viewer/dist with sourcemaps." >&2
    exit 1
  fi
}

write_runtime_package_json() {
  local target_dir="$1"
  cat > "$target_dir/package.json" <<EOF
{
  "name": "cad-viewer-runtime",
  "private": true,
  "type": "module",
  "version": "$RELEASE_VERSION",
  "scripts": {
    "start": "node server/main.mjs"
  }
}
EOF
}

write_runtime_gitignore() {
  local target_dir="$1"
  # node_modules stays ignored EXCEPT the vendored WASM kernel: the publish flow
  # is `git add -A`, which honours .gitignore, so anything the skill must ship
  # has to be tracked. The chain below re-includes only the four vendored files
  # (gitignore cannot re-include a file under an excluded directory, so each
  # ancestor directory is re-included and its other contents re-excluded).
  cat > "$target_dir/.gitignore" <<'EOF'
!node_modules/
node_modules/*
!node_modules/opencascade.js/
node_modules/opencascade.js/*
!node_modules/opencascade.js/LICENSE
!node_modules/opencascade.js/package.json
!node_modules/opencascade.js/dist/
node_modules/opencascade.js/dist/*
!node_modules/opencascade.js/dist/opencascade.full.js
!node_modules/opencascade.js/dist/opencascade.full.wasm
tmp

!dist
!dist/**
EOF
}

# Vendor the WASM STEP-import kernel (exactly the files ocKernel.mjs loads,
# plus its license and package.json for provenance) at the path the server
# resolves: <runtime>/node_modules/opencascade.js/. Real copies, never
# symlinks (check-builds.sh forbids symlinks in the publish tree).
vendor_wasm_kernel() {
  local target_dir="$1"
  local src_pkg="$VIEWER_DIR/node_modules/opencascade.js"
  if [ ! -f "$src_pkg/dist/opencascade.full.wasm" ] || [ ! -f "$src_pkg/dist/opencascade.full.js" ]; then
    echo "Missing opencascade.js kernel under $src_pkg/dist — run npm install in viewer/." >&2
    exit 1
  fi
  # Pin-check: the vendored kernel must be the version the committed lockfile
  # resolves (the WASM/native parity suites fence exactly that version).
  local installed locked
  installed="$(node -p "require('$src_pkg/package.json').version")"
  locked="$(node -p "require('$VIEWER_DIR/package-lock.json').packages['node_modules/opencascade.js'].version")"
  if [ "$installed" != "$locked" ]; then
    echo "opencascade.js version mismatch: installed $installed, lockfile pins $locked." >&2
    echo "Re-run npm install in viewer/ so the vendored kernel matches the pin." >&2
    exit 1
  fi
  local dest="$target_dir/node_modules/opencascade.js"
  mkdir -p "$dest/dist"
  cp "$src_pkg/LICENSE" "$dest/LICENSE"
  cp "$src_pkg/package.json" "$dest/package.json"
  cp "$src_pkg/dist/opencascade.full.js" "$dest/dist/opencascade.full.js"
  cp "$src_pkg/dist/opencascade.full.wasm" "$dest/dist/opencascade.full.wasm"
  write_third_party_notices "$target_dir" "$installed"
}

# Human-readable summary beside the vendored copy, following the
# _runtime/node THIRD_PARTY_LICENSES.txt pattern. The full LGPL-2.1 text ships
# as the vendored package's own unmodified LICENSE file.
write_third_party_notices() {
  local target_dir="$1"
  local kernel_version="$2"
  cat > "$target_dir/THIRD_PARTY_LICENSES.txt" <<EOF
This runtime vendors third-party code:

  opencascade.js $kernel_version (LGPL-2.1)
    https://github.com/donalffons/opencascade.js
    A WebAssembly build of Open CASCADE Technology (OCCT),
    https://dev.opencascade.org (LGPL-2.1 with OCCT exception).

The vendored files (node_modules/opencascade.js/dist/opencascade.full.js and
opencascade.full.wasm) are UNMODIFIED copies of the published npm package at
the version above; the full license text ships beside them as
node_modules/opencascade.js/LICENSE. Source for the wasm build is available
at the repository above at the same version tag.
EOF
}

build_runtime() {
  local target_dir="$1"
  rm -rf "$target_dir"
  mkdir -p "$target_dir"

  rsync -a --delete "$VIEWER_DIR/dist/" "$target_dir/dist/"
  # The server is plain dependency-free Node source, copied verbatim minus tests.
  rsync -a --delete --exclude "*.test.mjs" "$VIEWER_DIR/server/" "$target_dir/server/"

  write_runtime_package_json "$target_dir"
  write_runtime_gitignore "$target_dir"
  vendor_wasm_kernel "$target_dir"
}

check_runtime() {
  if [ -L "$RUNTIME_DIR" ]; then
    echo "CAD Viewer runtime is in development symlink layout; production runtime diff is checked post-bundle in CI."
    return
  fi
  if ! diff -qr "$CHECK_DIR" "$RUNTIME_DIR" >/tmp/cad-viewer-runtime-diff.txt; then
    cat /tmp/cad-viewer-runtime-diff.txt >&2
    echo "" >&2
    echo "CAD Viewer runtime is stale." >&2
    echo "Run scripts/bundle/bundle-skill.sh cad-viewer and commit skills/cad-viewer/scripts/viewer." >&2
    exit 1
  fi
  echo "CAD Viewer runtime is up to date."
}

require_command rsync
require_command node
if [ ! -f "$VIEWER_DIR/package.json" ]; then
  echo "Missing viewer app: $VIEWER_DIR" >&2
  exit 1
fi

if [ "$CLEAN" -eq 1 ]; then
  rm -rf "$CHECK_DIR"
fi

# In the development symlink layout there is nothing to diff against, so checking
# would only pay for a vite build whose output is then ignored.
if [ "$MODE" = "check" ] && [ -L "$RUNTIME_DIR" ]; then
  echo "CAD Viewer runtime is in development symlink layout; production runtime diff is checked post-bundle in CI."
  exit 0
fi

if [ "$BUILD" -eq 1 ]; then
  run_viewer_build
fi

if [ ! -f "$VIEWER_DIR/dist/index.html" ]; then
  echo "Missing viewer production bundle: $VIEWER_DIR/dist/index.html" >&2
  echo "Build it (drop --no-build, or run npm --prefix viewer run build -- --sourcemap true)." >&2
  exit 1
fi
require_client_sourcemaps "$VIEWER_DIR/dist"

if [ "$MODE" = "check" ]; then
  build_runtime "$CHECK_DIR"
  check_runtime
else
  build_runtime "$RUNTIME_DIR"
  echo "Bundled skills/cad-viewer/scripts/viewer"
fi
