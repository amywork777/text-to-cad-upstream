#!/usr/bin/env bash
set -euo pipefail

# Build cadgen's non-Python runtime INTO THE PACKAGE (packages/cadgen/src/cadgen/_runtime).
#
# cadgen executes three things it does not write in Python: Node builders (the DXF and
# implicit render packages are baked by a JS child), a headless browser bundle (the
# snapshot CLI drives it in a page), and the CAD Viewer's built SPA. They used to be
# generated once PER SKILL, beside each vendored copy of cadgen, because cadgen found them
# by walking up from its own __file__. cadgen.assets resolves them inside the distribution
# now, so there is one copy and one builder of that copy: this script.
#
# Despite living under skills/, this is not a skill bundler -- it is registered with
# bundle-skill.sh only so `--all`, `--check` and `--print-outputs` keep working uniformly.
#
# Stages (default: all of them):
#   --node      esbuilt builders          -> _runtime/node       (committed)
#   --browser   snapshot browser bundle   -> _runtime/browser    (committed)
#   --viewer    vite build of the SPA     -> _runtime/viewer     (GITIGNORED; CI/publish)
#
# The viewer stage is deliberately not committed: it is a 16 MB vite output that would
# churn on every client change. setuptools does not read .gitignore, so it still ships in
# the wheel whenever it is present on disk -- CI and the publish job both bundle before
# building the wheel. `--check` ignores it unless CADGEN_REQUIRE_VIEWER_DIST=1.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BUNDLE_REPO_ROOT="$REPO_ROOT"
# shellcheck source=../lib/node_builders.sh
source "$SCRIPT_DIR/../lib/node_builders.sh"
# shellcheck source=../lib/snapshot_runtime.sh
source "$SCRIPT_DIR/../lib/snapshot_runtime.sh"

RUNTIME_DIR="$REPO_ROOT/packages/cadgen/src/cadgen/_runtime"
NODE_DIR="$RUNTIME_DIR/node"
BROWSER_DIR="$RUNTIME_DIR/browser"
VIEWER_DIR="$RUNTIME_DIR/viewer"

VIEWER_SRC="$REPO_ROOT/viewer"
CHECK_DIR="${CADGEN_RUNTIME_CHECK_DIR:-$REPO_ROOT/tmp/cadgen-runtime-check}"
SNAPSHOT_BUILD_DEPS_DIR="${CADGEN_SNAPSHOT_BUILD_DEPS_DIR:-$REPO_ROOT/tmp/cadgen-snapshot-build}"

BUILDER_ENTRIES=(
  "$REPO_ROOT/packages/cadjs/bin/dxf-artifact.mjs"
  "$REPO_ROOT/packages/cadjs/bin/implicit-artifact.mjs"
  "$REPO_ROOT/packages/cadjs/bin/implicit-export.mjs"
  "$REPO_ROOT/packages/cadjs/bin/implicitClosureHooks.mjs"
  "$REPO_ROOT/packages/cadjs/src/lib/implicitCad/meshWorkerEntry.js"
)

MODE="write"
CLEAN=0
PRINT_OUTPUTS=0
STAGE_NODE=0
STAGE_BROWSER=0
STAGE_VIEWER=0
ANY_STAGE=0

usage() {
  cat <<'EOF'
Usage:
  scripts/bundle/bundle-skill.sh cadgen-runtime [--check] [--clean] [stages...]

Builds cadgen's packaged runtime assets into packages/cadgen/src/cadgen/_runtime.

Stages (default: all):
  --node      esbuilt Node builders     -> _runtime/node      (committed)
  --browser   snapshot browser bundle   -> _runtime/browser   (committed)
  --viewer    built CAD Viewer SPA      -> _runtime/viewer    (gitignored; CI/publish)

Options:
  --check          Rebuild into tmp/ and fail if the committed outputs are stale.
                   Skips the viewer stage unless CADGEN_REQUIRE_VIEWER_DIST=1.
  --clean          Remove the temporary check/build directories first.
  --print-outputs  Print committed output paths (repo-relative), then exit.
  -h, --help       Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --clean) CLEAN=1 ;;
    --print-outputs) PRINT_OUTPUTS=1 ;;
    --node) STAGE_NODE=1; ANY_STAGE=1 ;;
    --browser) STAGE_BROWSER=1; ANY_STAGE=1 ;;
    --viewer) STAGE_VIEWER=1; ANY_STAGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$ANY_STAGE" -eq 0 ]; then
  STAGE_NODE=1; STAGE_BROWSER=1; STAGE_VIEWER=1
fi

# The viewer output is not committed, so --check cannot demand it by default: a developer
# who has never bundled would fail a check for an artifact the repo does not track.
if [ "$MODE" = "check" ] && [ "${CADGEN_REQUIRE_VIEWER_DIST:-0}" != "1" ]; then
  STAGE_VIEWER=0
fi

# Only committed paths are declared: check-builds.sh asserts each exists, and _runtime/viewer
# legitimately does not on a fresh checkout.
if [ "$PRINT_OUTPUTS" -eq 1 ]; then
  printf '%s\n' \
    "${NODE_DIR#"$REPO_ROOT"/}" \
    "${BROWSER_DIR#"$REPO_ROOT"/}"
  exit 0
fi

if [ "$CLEAN" -eq 1 ]; then
  rm -rf "$CHECK_DIR"
fi

require_dir() {
  [ -d "$1" ] || { echo "Missing $2: $1" >&2; exit 1; }
}

# --- viewer -------------------------------------------------------------------------
VIEWER_PACKAGE_MANAGER="${CAD_VIEWER_PACKAGE_MANAGER:-}"

# The COMMITTED lockfile decides, not what happens to be installed on this machine. The
# repository commits viewer/package-lock.json, so preferring pnpm merely because it is on
# PATH made the release build depend on the builder's laptop: pnpm and npm lay out
# node_modules differently, so the same source revision could be bundled against a different
# tree. The committed npm lockfile is checked first on purpose: a stray local `pnpm install`
# leaves an untracked pnpm-lock.yaml behind, and that must not be able to flip a release
# build either. An explicit CAD_VIEWER_PACKAGE_MANAGER still wins -- someone deliberately
# switching should not have to delete a lockfile to do it.
resolve_viewer_package_manager() {
  if [ -n "$VIEWER_PACKAGE_MANAGER" ]; then
    echo "$VIEWER_PACKAGE_MANAGER"
    return
  fi
  if [ -f "$VIEWER_SRC/package-lock.json" ]; then
    echo "npm"
    return
  fi
  if [ -f "$VIEWER_SRC/pnpm-lock.yaml" ]; then
    echo "pnpm"
    return
  fi
  if command -v pnpm >/dev/null 2>&1; then
    echo "pnpm"
    return
  fi
  echo "npm"
}

build_viewer_dist() {
  local target="$1"
  if [ ! -f "$VIEWER_SRC/package.json" ]; then
    echo "Missing viewer app: $VIEWER_SRC" >&2
    return 1
  fi
  # Sourcemaps ship on purpose: an installed runtime is debuggable from browser DevTools.
  local package_manager
  package_manager="$(resolve_viewer_package_manager)"
  case "$package_manager" in
    pnpm) CI=true pnpm --dir "$VIEWER_SRC" run build --sourcemap true ;;
    npm)  npm --prefix "$VIEWER_SRC" run build -- --sourcemap true ;;
    *)
      echo "Unsupported CAD Viewer package manager: $package_manager" >&2
      echo "Set CAD_VIEWER_PACKAGE_MANAGER to pnpm or npm." >&2
      return 1
      ;;
  esac
  if [ ! -f "$VIEWER_SRC/dist/index.html" ]; then
    echo "vite build produced no $VIEWER_SRC/dist/index.html" >&2
    return 1
  fi
  rm -rf "$target"
  mkdir -p "$target"
  rsync -a --delete "$VIEWER_SRC/dist/" "$target/"
}

# --- third-party notices --------------------------------------------------------------
# The builders and the browser bundle inline three, meshoptimizer and gifenc. Shipping
# them inside a wheel is redistribution, and all three are MIT: the licence text has to
# travel with the copy. esbuild keeps the per-file banners (--legal-comments=eof); this is
# the human-readable summary beside them.
write_third_party_notices() {
  local target="$1"
  cat > "$target/THIRD_PARTY_LICENSES.txt" <<'EOF'
The JavaScript in this directory is bundled output. It inlines third-party code:

  three          (MIT)  https://github.com/mrdoob/three.js
  meshoptimizer  (MIT)  https://github.com/zeux/meshoptimizer
  gifenc         (MIT)  https://github.com/mattdesl/gifenc

Each bundle carries the originating licence banners at end of file
(esbuild --legal-comments=eof). Exact versions are pinned by
packages/cadjs/package-lock.json at the commit that produced these files.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF
}

build_all() {
  local root="$1"
  if [ "$STAGE_NODE" -eq 1 ]; then
    ensure_node_builder_deps
    bundle_node_builders "$root/node" "${BUILDER_ENTRIES[@]}"
    write_third_party_notices "$root/node"
    echo "Bundled ${root#"$REPO_ROOT"/}/node"
  fi
  if [ "$STAGE_BROWSER" -eq 1 ]; then
    ensure_snapshot_runtime_deps "$SNAPSHOT_BUILD_DEPS_DIR" 1
    build_snapshot_runtime "$root/browser" "$SNAPSHOT_BUILD_DEPS_DIR"
    write_third_party_notices "$root/browser"
    echo "Bundled ${root#"$REPO_ROOT"/}/browser"
  fi
  if [ "$STAGE_VIEWER" -eq 1 ]; then
    build_viewer_dist "$root/viewer"
    write_third_party_notices "$root/viewer"
    echo "Bundled ${root#"$REPO_ROOT"/}/viewer"
  fi
}

if [ "$MODE" = "check" ]; then
  rm -rf "$CHECK_DIR"
  mkdir -p "$CHECK_DIR"
  build_all "$CHECK_DIR"
  stale=0
  for stage in node browser viewer; do
    case "$stage" in
      node) [ "$STAGE_NODE" -eq 1 ] || continue ;;
      browser) [ "$STAGE_BROWSER" -eq 1 ] || continue ;;
      viewer) [ "$STAGE_VIEWER" -eq 1 ] || continue ;;
    esac
    label="packages/cadgen/src/cadgen/_runtime/$stage"
    if [ ! -d "$RUNTIME_DIR/$stage" ]; then
      echo "Missing generated cadgen runtime: $label" >&2
      stale=1
      continue
    fi
    diff_path="${TMPDIR:-/tmp}/cadgen-runtime-$stage-diff.txt"
    if ! diff -qr -x __pycache__ -x '*.pyc' "$CHECK_DIR/$stage" "$RUNTIME_DIR/$stage" >"$diff_path"; then
      cat "$diff_path" >&2
      echo "$label is stale." >&2
      stale=1
    else
      echo "$label is up to date."
    fi
  done
  if [ "$stale" -ne 0 ]; then
    echo "" >&2
    echo "Run scripts/bundle/bundle-skill.sh cadgen-runtime and commit the result." >&2
    exit 1
  fi
  echo "cadgen packaged runtime is up to date."
else
  mkdir -p "$RUNTIME_DIR"
  build_all "$RUNTIME_DIR"
fi
