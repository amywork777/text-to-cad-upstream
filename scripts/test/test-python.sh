#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/test/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

LIST_SKILLS_SCRIPT="$REPO_ROOT/scripts/utils/list-skills.sh"

# --keep-going: run every suite and report all of them, instead of stopping at the first
# failure. Opt-in, because stopping early is the right default for a developer waiting on a
# run. It is for CI on a platform being brought up, where the failures are independent and
# one round per suite means one ~10 minute round trip per suite.
KEEP_GOING=0
if [ "${1:-}" = "--keep-going" ]; then
  KEEP_GOING=1
  shift
fi
failed_suites=()

run_suite() {
  if [ "$KEEP_GOING" -eq 1 ]; then
    run_python_unittest "$@" || failed_suites+=("$1")
  else
    run_python_unittest "$@"
  fi
}

# The CAD Viewer backend suite, run EXACTLY as the standalone app's own CI runs it:
# `discover -s tests_server -t .` from the app directory. Not through
# run_python_unittest, and not with a path list of its own -- the app ships alone and
# validates itself with that one command, so reproducing it verbatim is what keeps the
# two runners from testing different sets.
#
# It lives in test-python.sh because it is a Python unittest suite and this is the
# repo's Python runner: from here it reaches the Linux `Run code tests` step through
# test.sh AND the Windows job, which calls this script directly. Windows matters most
# of all here -- the port moved path handling, locks, subprocesses and file URLs from
# Node to Python, which is precisely the class of bug that has only ever shown up on
# Windows.
#
# VIEWER_REQUIRE_CADGEN_PARITY turns the store-key equality guard from opportunistic
# into mandatory. That guard replaced ~190 lines of literal grep pins that used to run
# on every CI run; without the flag it is @skip-on-absent-cadgen, and the only other
# place it runs is the standalone app's CI, which has no cadgen by design -- so it
# would execute nowhere at all.
run_viewer_backend_suite() {
  section "CAD Viewer backend Python tests"
  # Fail closed, as run_python_unittest does: `unittest discover` exits 0 when it
  # collects nothing, so a renamed or emptied directory would otherwise report a green
  # suite that never ran -- which is the exact failure this whole arm exists to end.
  if [ -z "$(find "$REPO_ROOT/apps/viewer/tests_server" -name 'test*.py' -print -quit 2>/dev/null)" ]; then
    echo "No Python tests found under apps/viewer/tests_server" >&2
    return 1
  fi
  (
    cd "$REPO_ROOT/apps/viewer"
    PYTHONPATH="$REPO_ROOT/packages/cadgen/src${PYTHONPATH:+:$PYTHONPATH}" \
      VIEWER_REQUIRE_CADGEN_PARITY=1 \
      VIEWER_DISABLE_NATIVE_REVEAL=1 \
      "$PYTHON_BIN" -m unittest discover -s tests_server -t .
  )
}

cd "$REPO_ROOT"

# Turn the render-package write-lock assertion into a hard failure for tests. In
# production require_write_lock() only warns -- a missing lock must never be the reason a
# user's build fails -- so CI is the only place the contract is actually enforced.
export CADGEN_STRICT_LOCKS=1

# Isolate the shared caches (component store + op-memo disk tier) from the
# developer's real ~/.cache/cadgen: tests assert exact built/reused counts and
# byte-level outputs, and a populated user store would satisfy builds the test
# expects to run (and test runs would pollute the user's cache in return).
CADGEN_TEST_CACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cadgen-test-store.XXXXXX")"
trap 'rm -rf "$CADGEN_TEST_CACHE_DIR"' EXIT
export CADGEN_CACHE_DIR="$CADGEN_TEST_CACHE_DIR"

run_suite "cadgen package Python tests" "tests/python/packages/cadgen" "packages/cadgen/src"

while IFS= read -r skill; do
  test_dir="tests/python/skills/$skill"
  if [ -d "$test_dir" ]; then
    # Skills no longer vendor cadgen; they import the distribution. In a checkout that is
    # the repo's own source, so put it on the path rather than depending on whatever the
    # interpreter happens to have installed.
    run_suite "$skill skill Python tests" "$test_dir" \
      "skills/$skill/scripts" "packages/cadgen/src"
  fi
done < <("$LIST_SKILLS_SCRIPT")

if [ "$KEEP_GOING" -eq 1 ]; then
  run_viewer_backend_suite || failed_suites+=("CAD Viewer backend Python tests")
else
  run_viewer_backend_suite
fi

if [ "${#failed_suites[@]}" -gt 0 ]; then
  printf '\n==> FAILING SUITES (%d)\n' "${#failed_suites[@]}"
  printf '  %s\n' "${failed_suites[@]}"
  exit 1
fi
