#!/usr/bin/env bash
# Exercise cadgen the way a user gets it: built into a wheel, pip-installed, run from a
# directory that is not this repo.
#
# Every other check in this repo runs against the source tree, where the repo root is on
# sys.path, `packages/cadjs/bin` exists, and `viewer/dist` is one directory away. None of
# that is true after `pip install cadgen`, so the failures this catches are exactly the
# ones no other check can: an asset left out of package-data, a module that resolves only
# because a sibling directory happened to be adjacent, a builder that still imports a bare
# specifier. Those all pass locally and break for the person who installed it.
#
# The scratch venv reuses the repo venv's heavy dependencies (OCP, build123d) rather than
# reinstalling half a gigabyte -- but the wheel's own cadgen must WIN over the repo's
# editable one, or this would silently test the source tree again. See _link_repo_deps.
#
# Usage: scripts/test/test-installed.sh [--keep]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Shared resolution: the repo venv in a checkout, python3 otherwise. CI installs the CAD
# dependencies into the interpreter that setup-python provides and has no .venv at all, so
# hardcoding one here fails there and only there.
# shellcheck source=scripts/test/common.sh
source "$SCRIPT_DIR/common.sh"

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
  echo "No usable Python ($PYTHON_BIN). Set PYTHON_BIN to an interpreter with the CAD deps." >&2
  exit 1
fi

# The wheel is installed with --no-deps and reuses this interpreter's heavy packages, so it
# must actually have them; otherwise the failure surfaces much later as a viewer that will
# not bind its port.
if ! "$PYTHON_BIN" -c "import OCP, build123d" >/dev/null 2>&1; then
  echo "$PYTHON_BIN cannot import OCP/build123d; installed-mode checks need the CAD deps." >&2
  exit 1
fi

WORK="$(mktemp -d)"
cleanup() { [ "$KEEP" -eq 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT
[ "$KEEP" -eq 1 ] && echo "Keeping $WORK"

VENV="$WORK/venv"
EMPTY="$WORK/empty"
DIST="$WORK/dist"
mkdir -p "$EMPTY" "$DIST"

fail() { echo "FAIL: $*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

step "Build the wheel"
# The viewer client is gitignored, so a wheel built from a tree that was never bundled has
# no SPA in it. Require it here rather than discovering it after publish.
CADGEN_REQUIRE_VIEWER_DIST=1 "$REPO_ROOT/scripts/bundle/bundle-skill.sh" cadgen-runtime >/dev/null
"$PYTHON_BIN" -m build --wheel --outdir "$DIST" "$REPO_ROOT/packages/cadgen" >"$WORK/build.log" 2>&1 \
  || { cat "$WORK/build.log" >&2; fail "wheel build"; }
WHEEL="$(find "$DIST" -name '*.whl' -type f | head -n 1)"
[ -n "$WHEEL" ] || fail "no wheel produced"
echo "   $(basename "$WHEEL")"

step "Install it into a scratch venv"
"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --no-deps "$WHEEL"

_link_repo_deps() {
  # Expose the repo venv's site-packages for OCP/build123d/etc WITHOUT letting its editable
  # cadgen win. A plain path line in a .pth is sys.path.append, so it lands AFTER this
  # venv's own site-packages (where the wheel is) and its .pth files are not processed --
  # which is what keeps the editable cadgen out.
  local repo_sp scratch_sp
  repo_sp="$("$PYTHON_BIN" -c 'import site; print(site.getsitepackages()[0])')"
  scratch_sp="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
  printf '%s\n' "$repo_sp" >"$scratch_sp/zz-repo-deps.pth"
}
_link_repo_deps

step "The installed cadgen is the WHEEL's, not the checkout's"
"$VENV/bin/python" - <<'PY' || exit 1
import sys, pathlib, cadgen
where = pathlib.Path(cadgen.__file__).resolve()
if "site-packages" not in where.parts:
    sys.exit(f"FAIL: imported cadgen from {where}, not the installed wheel")
print(f"   {cadgen.__version__} at {where.parent}")
PY

step "Assets resolve to the packaged runtime"
"$VENV/bin/python" - <<'PY' || exit 1
import sys
from cadgen.assets import browser_runtime_dir, node_builders_dir, viewer_dist_dir
for label, resolved in (
    ("node builders", node_builders_dir()),
    ("browser runtime", browser_runtime_dir()),
    ("viewer dist", viewer_dist_dir()),
):
    if "site-packages" not in str(resolved):
        sys.exit(f"FAIL: {label} resolved outside the wheel: {resolved}")
    if not resolved.is_dir():
        sys.exit(f"FAIL: {label} missing: {resolved}")
    print(f"   {label}: {resolved.name}")
PY

step "Every subcommand dispatches from an empty directory"
cd "$EMPTY"
"$VENV/bin/cadgen" --help >/dev/null || fail "cadgen --help"
while read -r command; do
  [ -n "$command" ] || continue
  # shellcheck disable=SC2086
  "$VENV/bin/cadgen" $command --help >/dev/null 2>&1 || fail "cadgen $command --help"
  echo "   cadgen $command"
done <<'COMMANDS'
step gen
step artifact
step export
step inspect
step snapshot
dxf gen
dxf artifact
dxf snapshot
implicit gen
implicit export
implicit snapshot
snapshot
viewer
COMMANDS

step "Build a real STEP with no repo in sight"
mkdir -p "$EMPTY/models"
cat >"$EMPTY/models/probe.step.py" <<'PY'
# A .step.py target is a module exposing gen_step() -> shape. Deliberately the simplest
# one that exists: this checks that an installed cadgen can build at all, not that it
# models anything interesting.
from build123d import Box


def gen_step():
    return Box(10, 10, 10)
PY
"$VENV/bin/cadgen" step gen models/probe.step.py >"$WORK/gen.log" 2>&1 \
  || { cat "$WORK/gen.log" >&2; fail "cadgen step gen"; }
find "$EMPTY/models" -name '*.glb' -o -name '*.step' | head -1 | grep -q . \
  || { cat "$WORK/gen.log" >&2; fail "step gen produced no artifact"; }
echo "   built a STEP package"

step "Serve the viewer and answer a catalog request"
PORT="$("$VENV/bin/python" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
"$VENV/bin/cadgen" viewer --host 127.0.0.1 --port "$PORT" >"$WORK/viewer.log" 2>&1 &
VIEWER_PID=$!
# `wait` after the kill so bash reaps the child quietly; without it the shell prints a
# "Terminated" job notice AFTER the success line, which reads like a failure.
trap 'kill "$VIEWER_PID" 2>/dev/null || true; wait "$VIEWER_PID" 2>/dev/null || true; cleanup' EXIT

for _ in $(seq 1 60); do
  curl -fsS -m 2 "http://127.0.0.1:$PORT/__cad/server" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS -m 5 "http://127.0.0.1:$PORT/__cad/server" >/dev/null \
  || { cat "$WORK/viewer.log" >&2; fail "viewer did not come up"; }
curl -fsS -m 10 "http://127.0.0.1:$PORT/" | grep -qi '<title>' \
  || fail "viewer served no SPA (is the client bundled into the wheel?)"
curl -fsS -m 20 "http://127.0.0.1:$PORT/__cad/catalog?dir=$EMPTY/models" | grep -q 'probe' \
  || fail "catalog did not list the generated model"
echo "   SPA + catalog OK on port $PORT"

printf '\nInstalled-mode checks passed.\n'
