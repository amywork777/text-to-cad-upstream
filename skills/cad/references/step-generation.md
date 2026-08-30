# STEP generation

Read this file when generating or regenerating STEP/STP artifacts from build123d
Python source, or when working with imported STEP/STP files.

## The model script is the tool

Generation has no CLI. A model is a plain Python script that builds itself:

```python
from cadgen import build123d as bd
from cadgen import step

@step()
def bracket(width: float = 10.0):
    return bd.Box(width, 10, 10)
```

```bash
python bracket.py                 # builds bracket.step + its render package
python bracket.py --force --json  # per-run flags ride the script's argv
```

Every run keeps the model's render package (the document of record: exact-shape
`.brep` blobs + `.surf` render views + descriptor, in the user-level store keyed by the document's content hash)
current and ALWAYS writes the `.step` output, assembled from that package rather
than re-generated. Unchanged sources are a fast no-op. The default output is the
sibling `<stem>.step`; relocate it durably with `@step(write="path/to/out.step")`
(relative to the script) or per-run with `-o PATH` (relative to the command cwd).
Do not put output paths in the model's return value. `cadgen step export` writes
mesh formats only (see `supported-exports.md`).

Rules the decorator enforces:

- **Import never builds.** Only running the script as `__main__` builds;
  importing the module registers the model, and calling the function returns
  the shape. This is what makes composition and testing ordinary Python.
- **Decoration-time execution.** Everything the model needs (helpers,
  constants, imports) must be defined ABOVE the decorated function.
- **One model per file.** The file is the model; entry identity, packages, and
  closures key off it.
- **Parameters must all have defaults** — the pipeline calls the function with
  no arguments; defaults are the authored values.
- Options: `write=`, `kind="part"|"assembly"` (else inferred from the return),
  `mesh_tolerance=`, `mesh_angular_tolerance=`. Envelope returns
  (`{"shape": ..., "params": ..., "stl": ..., "3mf": ...}`) keep working.

**Imports:** `from cadgen import build123d as bd` is the canonical import — a
lazy, transparent re-export (same names, same objects on first touch), so a
current model's re-run never pays the ~2.5s kernel import: the freshness gate
and warm-daemon handoff fire before any `bd.` attribute resolves. Raw
`import build123d` still works, just slower on re-runs (the decorator prints a
one-line hint).

Legacy `gen_step()`/`gen_dxf()` sources and `.step.py`/`.dxf.py` naming fail
hard with a pointer to `migrating-generators.md` (codemod:
`python -m cadgen.migrate <file>`).

## Generated vs imported STEP

These two terms classify a STEP file by what its source is:

- A **generated STEP file** has a model script as its source. The STEP and its
  render package are *derived*; the script is what you edit and re-run.
- An **imported STEP file** is its own source: authored or downloaded
  elsewhere. There is nothing upstream to regenerate.

The link between an artifact and its script is the source sidecar generation
writes BESIDE THE MODEL (`<name>.step.source.json`, carrying `sourcePath`,
source hashes, pose, and mates), and that sidecar's existence is what marks a
model as generated; imports write none.
The written STEP/DXF file itself carries NO cadgen metadata and no link back
to source code, ever — a bare artifact separated from its package is a plain
importable file. Provenance is never inferred from filenames either — so
relocated outputs, renamed scripts, and shared output folders all stay
traceable through the package alone.

When a generated model builds on another STEP file, that file is a
**dependency** (see "Child dependencies" in `positioning.md`).

## Model scripts, helpers, and composition

A **model script** is any plain `.py` defining one `@step` (or `@dxf`)
function. **Helper/library modules** (shared geometry functions, `_parts.py`,
`*_common.py`) are ordinary undecorated Python — import them normally. Only
decorated scripts are buildable entries; helpers never appear in the viewer
catalog no matter what they are named. Prefer an underscore prefix
(`_fasteners.py`) to make the split obvious at a glance.

Because model scripts are plain `.py`, they are real importable modules:
`import bracket; bracket.bracket()` returns the shape with no build side
effects. For assembly composition prefer **`cadgen.compose.child_entry`** — the
traced, cached seam. Each child's model function becomes a SCOPE keyed by its
own source closure: an edit that does not reach a child's files skips that
child's Python and kernel work entirely (this is what makes big-assembly edits
cost seconds instead of minutes), and the seam owns the child's `sys.path`
context so its sibling-helper imports resolve regardless of working directory:

```python
from pathlib import Path

from cadgen import build123d as bd
from cadgen import step
from cadgen.compose import child_entry

_HERE = Path(__file__).resolve().parent
_WIDGET = child_entry(_HERE / "widget.py")

@step(kind="assembly")
def rig():
    widget = _WIDGET.widget()   # cached scope; compose into the parent
    widget.label = "widget"
    ...
```

Expensive helper FUNCTIONS inside one entry can opt into the same caching with
`@cadgen.compose.memo` (pure functions of their arguments and source closure,
returning shapes/compounds).

**`sys.path` does not survive into the model function.** The pipeline restores
`sys.path` after loading the module, so import sibling helpers at module top
level and only *call* them inside the function.

For structuring multi-part projects (folder layout, shared `src/` code, commit
policy), load the `$cad-project` skill.

## Generated assemblies

Kind is inferred from the return value (a labeled `Compound` with children
reads as an assembly) or declared with `@step(kind="assembly")`. Passing a
generated assembly's exported `.step` to a tool treats it as imported native
STEP and loses source-level composition; work with the `.py` source. Prefer
`cadgen.assembly.AssemblyHelper` so native labels, named mate frames, and
source-level relationships are preserved before STEP export (see
`positioning.md`).

## Imported STEP/STP files

An imported STEP/STP file needs no model script. Build its render package once
with `cadgen step build`; `cadgen step inspect` and `cadgen step snapshot` also build it
on demand, and its part/assembly kind is inferred from the STEP product
hierarchy. (The CAD Viewer's in-app import spawns this same
`cadgen step build` under the hood — one producer, one package format.)

```bash
cadgen step build path/to/imported.step [--force]
```

To produce STL/3MF/native GLB files from an imported STEP, pass it directly to
`cadgen step export`; read `supported-exports.md`.

## Optional-module generators and the artifact cache

A model that imports several part modules and SKIPS the ones that do not exist
yet is a useful pattern for parallel work — the assembly stays renderable while
individual parts are still being written. It has one sharp edge.

The artifact's source-closure hash is computed from the modules the model
ACTUALLY IMPORTED at build time. Modules that did not exist during the first
build were never in the closure, so their later appearance cannot change the
hash. The cache is self-consistent and permanently stale: tools that resolve
artifacts on demand keep serving the old package, with no error and no warning,
long after the new modules land.

Run the model script explicitly after adding a part module, rather than relying
on implicit resolution by `inspect`, `snapshot`, or the Viewer.

## Viewer artifacts

Every model run writes the hidden adjacent render package as the build output.
It powers CAD Viewer review, `$cad-viewer` workflows, and `cadgen step inspect`
refs, and is not optional in the STEP workflow. Imported STEP/STP files get the
same package via `cadgen step build` or on demand, per the previous section.

## After generation

- Confirm the process succeeded and the STEP file exists and is non-empty.
- Run the baseline inspection and any spec-driven checks per
  `inspection-and-validation.md`:

```bash
cadgen step inspect refs path/to/model.step --facts --planes --positioning
```

## Warm daemon (on by default)

Every model run and `cadgen step export` / `cadgen step build` / `cadgen step inspect` /
`cadgen step snapshot` invocation would otherwise pay a multi-second OCP/build123d
import. They are routed through a shared warm daemon **by default** — the
decorator hands a directly-run script to the daemon before any kernel import —
and `CADGEN_DAEMON=0` forces the cold path:

```bash
python path/to/part.py            # warm, no flag needed
CADGEN_DAEMON=0 python part.py      # force a cold in-process run
```

- The daemon is a **supervisor over a pool of warm worker processes**. It never imports
  OCP itself, so a model that crashes the CAD kernel costs one worker rather than the
  daemon. The first call spawns a worker (paying the import once); later calls run in a
  warm one and stream the CLI's stdout/stderr and exit code back unchanged.
- **Parallel builds are supported.** A burst spawns workers up to a cap, and a second
  burst reuses the first's workers, so repeated parallel work converges to warm.
- **The cap follows the machine**: the smaller of what memory allows (half of RAM, or the
  cgroup limit inside a container, divided by ~300 MB a warm worker holds) and what the
  cores allow (`cores - 2`), never more than 32. `CADGEN_DAEMON_MAX_WORKERS` overrides.
- **At the cap a caller waits briefly**, then runs cold if nothing frees up —
  `CADGEN_DAEMON_WAIT`, default 2s; 0 gives up immediately. Jobs are usually short next
  to an OCP import, so most waits end in a warm worker.
- `cadgen daemon status` reports `waits` and `coldOverflows`. Overflows climbing during
  normal work means the machine is genuinely saturated, not that the cap is too small.
- Directly-run model scripts and the `cadgen` commands share the same warm processes.
  (The CAD Viewer runs no Python and never builds; it only reflects CLI builds via their
  progress records.)
- **It runs on Windows too.** The channel is a Unix socket on macOS and Linux and a named
  pipe on Windows, both through `multiprocessing.connection` and ACL'd to their creator.
- The daemon is **per worktree**, keyed by `sha256(cadgen-dir)[:12]`; a `.log` beside the
  socket holds daemon lifecycle and C-level OCP noise. `CADGEN_DAEMON_SOCKET` overrides.
- **Staleness:** the daemon records a version token at startup; when a client's token
  differs — cadgen changed — it exits and the client transparently respawns a fresh one.
- **Idle exit:** workers reap down to one after 5 minutes idle; the daemon exits after 10
  minutes without a request (`CADGEN_DAEMON_IDLE_TIMEOUT` overrides).
- On any daemon spawn or protocol problem the run silently falls back to a cold
  in-process build. A cold `@dxf` run re-execs once with `PYTHONHASHSEED=0` so drawing
  bytes stay deterministic.
