# cadgen design laws

Internal development document. Read this before changing generation,
rendering, storage, or any public interface. These are LAWS, not
conventions: a change that violates them is wrong even when it works, and
each carries a pressure-test to apply to a proposed design before writing
code.

## 1. Generated files are totally independent of their source code

A generated file (STEP, DXF, STL, GLB, 3MF) and its generated sidecar
(`<name>.step.cadgen.json`) stand alone, forever, with no dependency of any
kind on the source that produced them.

**Pressure-test**: a generated file must be fully renderable — viewer,
snapshot, inspect — by reading ONLY (a) the generated file(s), including the
generated sidecar, and (b) the cache. Never the source. If the cache is
missing or evicted, cadgen may regenerate cache artifacts, but ONLY from the
generated file's own bytes (`cadgen step compile` semantics): regeneration
never maps back to source code. Deleting every `.py` in a project must not
change what renders.

Concretely:

- A STEP file never refers back to its source. Neither does anything a
  renderer reads: the sidecar's kinematics section is resolved numbers and
  labels, its animation section is COPIED module text — no path, import, or
  reference into the source tree ever appears in a generated file.
- The sidecar's closure fields (source path and content hashes) are
  BOOKKEEPING FOR THE SOURCE-SIDE NO-OP GATE ONLY. Rendering logic must
  never read them, and staleness is never acted on by rendering or by any
  document door — a stale document at a CLI is at most a teaching error
  naming `python <script>`; nothing auto-rebuilds from source.
- Source scripts are PROGRAMS: they are run (`python model.py`), never
  passed to CLIs, never parsed by renderers, never discovered by scans.

## 2. The cache contains only format-derived build and render artifacts

The cache (`~/.cache/cadgen`) holds data derivable from a generated file's
bytes — render packages, tessellations, freshness records — and nothing
else. No sidecars, no authored context, no source-derived state.

**Pressure-test**: everything in the cache must be (a) a pure function of
some file's bytes plus schema versions, (b) safely deletable at any time,
and (c) rebuildable from generated files alone. If losing a cache entry
would lose information — kinematics, animation, provenance — that
information is in the wrong place: authored context lives in the sidecar
BESIDE the file it describes, and travels with it.

The dividing line, stated once: **the cache is what the bytes imply; the
sidecar is what the author meant.**

## 3. Decorators, public functions, and CLIs are one surface, kept in sync

Every capability appears as a rigidly aligned triple: the DECORATOR declares
it on a model, the PUBLIC FUNCTION (`cadgen.<format>.<verb>`) performs it
from Python, and the CLI (`cadgen <format> <verb>`) is GENERATED from that
function's signature — never hand-written, so a flag cannot exist without a
parameter or drift from one (`cadgen._internal.cli_from_function`;
structural sync tests pin `function_parameters == parser_dests` per
command).

**Pressure-test**: for any option, ask "what is this called on the other two
surfaces?" The answer must be the same name with a role-determined payload —
e.g. `kinematics` everywhere: on DECLARING surfaces (decorators,
`step build`) it is the space (the mates/couplings/poses/at dict); on
CONSUMING surfaces (snapshot, mesh `build`) it is a point in that space (a
preset name or `{dof: value}`). One name, one validator, no synonyms, no
per-surface dialects. When a surface retires, it fails with a teaching error
naming its replacement — never a silent alias, never a compatibility shim
(the standing no-backcompat rule).
