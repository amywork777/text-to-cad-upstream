"""The drawing pipeline's byte-determinism invariant, in one place.

A drawing package is content-addressed and ezdxf's object ordering depends on
hash randomization, so the SAME source must write the SAME `.dxf` bytes on every
run. ``PYTHONHASHSEED`` is read at interpreter start, which means a process that
did not start with it pinned cannot fix itself — it has to re-run.

Three callers need this and they used to say it three different ways (the
retired `dxf gen` dispatch, the `@dxf` decorator's direct-run path, and nothing
at all on the CLI side, which is how `cadgen dxf build` could have shipped
non-deterministic):

* ``cadgen.authoring`` — a directly executed `@dxf` model script.
* ``cadgen.cli`` dispatch — ``cadgen dxf build``, re-run BEFORE the command's
  module is imported.
* the warm daemon — already exempt: every worker is spawned with the seed
  pinned, so a served build never pays an interpreter restart.

subprocess rather than an exec-replacement, for the reason #245 hit: on Windows
``execv`` hands the argument VECTOR to the C runtime, which re-joins it without
quoting, so an interpreter path containing a space arrives as two arguments.
subprocess applies Windows quoting rules, and nothing is lost on POSIX because
that call never replaced the process on Windows anyway.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence

#: What a deterministic drawing build runs with.
STABLE_HASH_SEED = "0"


def hash_seed_is_stable(env: "dict[str, str] | None" = None) -> bool:
    """True when this interpreter already started with the seed pinned."""
    source = os.environ if env is None else env
    return source.get("PYTHONHASHSEED") == STABLE_HASH_SEED


def rerun_with_stable_hash_seed(argv: Sequence[str]) -> int:
    """Re-run ``argv`` under this interpreter with the seed pinned; RETURN its code.

    The exit code must reach the original caller or every failed generator would
    read as a success. ``CADGEN_DAEMON=0`` rides along because cold was already
    decided: bouncing the re-run to the daemon would undo the decision that made
    it necessary.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = STABLE_HASH_SEED
    env["CADGEN_DAEMON"] = "0"
    return subprocess.run([sys.executable, *argv], env=env, check=False).returncode
