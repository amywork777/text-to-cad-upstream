# STEP generation

Read this file when generating or regenerating STEP/STP artifacts from build123d Python source, or when working with imported STEP/STP files.

## Tools

The launchers live in the CAD skill directory:

```bash
python scripts/gen targets... [flags]     # build render GLB/topology packages from gen_step() sources
python scripts/export target [flags]      # write STL/3MF/GLB mesh files (see supported-exports.md)
```

`scripts/gen` accepts gen_step() Python generator sources only. Use explicit target paths only; target paths resolve from the command cwd unless absolute. Do not rely on directory-wide generation.

`scripts/gen` is source-in, STEP-out: every run keeps the model's render package (the document of record: exact-shape `.brep` blobs + `.surf` render views + descriptor) current and ALWAYS writes the `.step` output, assembled from that package rather than re-generated. The default output is each target's sibling `<name>.step`; `-o PATH` renames it (single target, resolved from the command cwd). Unchanged sources are a no-op. `scripts/export` writes mesh formats only. Do not put output paths in the `gen_step()` return value; the CLI flags own output paths.

## Generated vs imported STEP

These two terms classify a STEP file by what its source is, and they drive every workflow decision in this skill:

- A **generated STEP file** has a Python generator script as its source — a `.step.py` (a `.py` that defines `gen_step()`). The STEP and its GLB/topology artifacts are *derived* from that script, so the script is what you edit and regenerate; the `.step` is an output.
- An **imported STEP file** is its own source: a STEP/STP authored or downloaded elsewhere, not derived from any generator script. There is nothing upstream to regenerate — the STEP file itself is the source of truth.

When a generated STEP file's `gen_step()` builds on another STEP file, that other file is a **dependency** of the generator (ordinary code-dependency terms apply: the parent depends on the child). How you wire a dependency in depends on whether the child is generated or imported — see "Child dependencies" in `positioning.md`.

## Entry generators are named `<name>.step.py`

A **STEP entry generator** — a Python script that defines `gen_step()` and is meant to be built, inspected, snapshotted, or shown in the viewer on its own — is named `<name>.step.py`. That filename is the marker the viewer catalog and the build tools scan for. Ordinary **helper / library modules** (shared geometry functions, `*_parts/` packages, `*_common.py`, anything imported by other generators but not built on its own) stay `<name>.py` and are NOT treated as entries even if they define `gen_step` — the viewer scans for `.step.py`, not every Python file. So: if a `.py` script is a buildable model on its own, name it `<name>.step.py`; if it only exists to be imported by other generators, leave it `<name>.py`.

- A `<name>.step.py` entry produces the logical STEP `<name>.step` (the filename minus the trailing `.py`); its render package lives at `<dir>/__cadgen__/models/<name>.step.py/`. Build/inspect it by passing the `.step.py` path to the CLI, exactly like any generator source.
- **A `.step.py` file cannot be imported by name.** `import foo` does not find `foo.step.py`, and `import foo.step` makes Python look for a `foo` package (a `foo/` directory) — neither exists. Load an entry generator by PATH (`importlib.util.spec_from_file_location`), which is how the CLI, the viewer, and assembly composition already load generators. If generators must share constants/functions, put the shared code in a plain `<name>.py` helper they both import, or path-load the entry. When a generated assembly composes a generated child (see "Child dependencies" in `positioning.md`), it path-loads the child `.step.py` and calls its `gen_step()` — it never `import`s it by name.

  **`sys.path` does not survive into `gen_step()`.** The CLI restores `sys.path`
  after loading your generator module, so a path inserted at import time is gone
  by the time `gen_step()` runs — an import attempted inside the function fails
  with a bare `No module named ...` that points at the module rather than at the
  path. Import sibling helper modules at module top level and only *call* them
  inside `gen_step()`.

  **Compose children through `cadgen.compose.child_entry`** — the traced,
  cached seam. Each child's `gen_step()` becomes a SCOPE keyed by its own
  source closure: an edit that does not reach a child's files skips that
  child's Python and kernel work entirely (this is what makes big-assembly
  edits cost seconds instead of minutes). The seam also owns the child's
  `sys.path` context, so its sibling-helper imports resolve regardless of
  the working directory:

  ```python
  from pathlib import Path

  from cadgen.compose import child_entry

  _HERE = Path(__file__).resolve().parent
  _WIDGET = child_entry(_HERE / "widget.step.py")

  def gen_step():
      widget = _WIDGET.gen_step()   # cached scope; compose into the parent
      widget.label = "widget"
      ...
  ```

  Expensive helper FUNCTIONS inside one entry can opt into the same caching
  with `@cadgen.compose.memo` (pure functions of their arguments and source
  closure, returning shapes/compounds). A raw
  `importlib.util.spec_from_file_location` path-load still works but gets no
  caching and must manage `sys.path` itself; prefer `child_entry`.

## Generated Python source

This is the default path when designing from scratch or modifying a generated model. Generated build123d sources define:

```python
def gen_step():
    ...
    return step_ready_shape_or_labeled_compound
```

Generated Python targets infer their kind from the source metadata and `gen_step()` return value; pass the source path directly:

```bash
python scripts/gen path/to/part.step.py
python scripts/gen path/to/a.step.py path/to/b.step.py
python scripts/gen path/to/assembly.step.py
```

Passing a generated assembly's exported `.step` to a tool treats it as imported native STEP and loses source-level assembly composition; work with the `.py` assembly source. For generated build123d assemblies, prefer `cadgen.assembly.AssemblyHelper` in the Python source so native labels, named mate frames, and source-level relationships are preserved before STEP export (see `positioning.md`).

## Imported STEP/STP files

An imported STEP/STP file (downloaded or authored elsewhere, no generator) needs no build command. Its GLB/topology render artifacts are generated on demand from the STEP file itself by the tools that consume them — `scripts/inspect`, `scripts/snapshot`, and the CAD Viewer — and its part/assembly kind is inferred from embedded metadata or the STEP product hierarchy.

To produce STL/3MF/native GLB files from an imported STEP, pass it directly to `scripts/export`; read `supported-exports.md`.

To debug or pre-run the on-demand render-package build itself, `scripts/artifact` runs exactly one build for an imported STEP/STP file (or a generator source) and prints the result payload:

```bash
python scripts/artifact path/to/imported.step [--kind part|assembly] [--force]
```

## Optional-module generators and the artifact cache

A generator that imports several part modules and SKIPS the ones that do not
exist yet is a useful pattern for parallel work — the assembly stays renderable
while individual parts are still being written. It has one sharp edge.

The artifact's source-closure hash is computed from the modules the generator
ACTUALLY IMPORTED at build time. Modules that did not exist during the first
build were never in the closure, so their later appearance cannot change the
hash. The cache is self-consistent and permanently stale: tools that resolve
artifacts on demand keep serving the old package, with no error and no warning,
long after the new modules land.

Run `scripts/gen` on the entry explicitly after adding a part module, rather than
relying on implicit resolution by `inspect`, `snapshot`, or the Viewer.

## Viewer artifacts

Every `scripts/gen` run writes hidden adjacent GLB/topology artifacts as the build output. They power CAD Viewer review, `$cad-viewer` workflows, and `scripts/inspect` refs, and are not optional in the STEP workflow. Imported STEP/STP files get the same artifacts on demand, per the previous section.

## After generation

- Confirm the process succeeded and the STEP file exists and is non-empty.
- Run the baseline inspection and any spec-driven checks per `inspection-and-validation.md`:

```bash
python scripts/inspect refs path/to/model.step --facts --planes --positioning
```

## Warm daemon (opt-in)

Every `scripts/gen` / `scripts/export` / `scripts/artifact` / `scripts/inspect`
/ `scripts/snapshot` invocation would otherwise pay a multi-second OCP/build123d
import. They are routed through a shared warm daemon **by default**; set
`CADGEN_WARM=0` to force the cold path.

```bash
python scripts/gen path/to/part.step.py     # warm, no flag needed
CADGEN_WARM=0 python scripts/gen part.step.py   # force a cold in-process run
```

- The daemon is a **supervisor over a pool of warm worker processes**. It never imports
  OCP itself, so a model that crashes the CAD kernel costs one worker rather than the
  daemon. The first call spawns a worker (paying the import once); later calls run in a
  warm one and stream the CLI's stdout/stderr and exit code back unchanged.
- **Parallel builds are supported.** A burst spawns workers up to a cap, and a second
  burst reuses the first's workers, so repeated parallel work converges to warm. This is a
  change: the daemon used to hold exactly one job, which is why parallel builders were
  told to avoid it.
- **The cap follows the machine**: the smaller of what memory allows (half of RAM, or the
  cgroup limit inside a container, divided by ~300 MB a warm worker holds) and what the
  cores allow (`cores - 2`), never more than 32. A 64 GB workstation gets 30 where it used
  to get 4. `CADGEN_DAEMON_MAX_WORKERS` overrides it outright.
- **At the cap a caller waits briefly**, then runs cold if nothing frees up —
  `CADGEN_DAEMON_WAIT`, default 2s, and 0 restores the old give-up-immediately behaviour.
  Jobs are usually short next to an OCP import, so most waits end in a warm worker. The
  wait is what makes the cap mean anything: without it every overflow caller starts its
  own OCP process, so the pool bounded nothing.
- `cadgen daemon status` reports `waits` and `coldOverflows`. Overflows climbing during
  normal work means the machine is genuinely saturated, not that the cap is too small.
- Both front doors use it — `scripts/gen` and `cadgen step gen` alike — and so does the
  CAD Viewer, so a terminal build and a viewer build share the same warm processes.
- **It runs on Windows too.** The channel is a Unix socket on macOS and Linux and a named
  pipe on Windows, both through `multiprocessing.connection`, so warm builds are not a
  POSIX-only feature. A named pipe is ACL'd to its creator exactly as a Unix socket takes
  its permissions from the filesystem — a loopback TCP port would have been reachable by
  any local process, which is not a property to give up on a channel that runs code.
- The daemon is **per worktree**, keyed by `sha256(cadgen-dir)[:12]`:
  `<tempdir>/cadgen-daemon/cadgen-daemon-v<protocol>-<key>.sock` on POSIX, and
  `\\.\pipe\cadgen-daemon-v<protocol>-<key>` on Windows. A `.log` file holds daemon
  lifecycle and C-level OCP noise. `CADGEN_DAEMON_SOCKET` overrides the address, and means
  a path or a pipe name depending on the platform. The address carries a protocol version,
  so a client never reaches a daemon speaking an older wire format — it starts its own and
  the old one idles out.
- **Staleness:** the daemon records a version token at startup. When a client's token
  differs — i.e. cadgen changed — the daemon exits and the client transparently respawns
  a fresh one, so edits to runtime code always take effect on the next call.
- **Idle exit:** workers reap down to one after 5 minutes idle, and the daemon exits
  after 10 minutes without a request (`CADGEN_DAEMON_IDLE_TIMEOUT` seconds overrides).
- On any daemon spawn or protocol problem the CLI silently falls back to a cold
  in-process run. Invocations reading a payload from stdin (e.g. `scripts/snapshot
  --job -`) always run cold.
