# Library-first generation: decorators replace the gen CLI

## End state

A CAD model is a plain Python script an agent runs directly. No CLI, no magic
function name, no boilerplate main:

```python
from cadgen import build123d as bd
from cadgen import step

@step(write="bracket.step", kind="part", mesh_tolerance=8e-4)
def bracket(width: float = 10.0):
    return bd.Box(width, 10, 10)
```

`python bracket.py` builds the model through the EXACT runtime the gen CLI
drives today — freshness gate, warm daemon, locks/progress records, incremental
package build, tessellation caches. Durable configuration (output path, kind,
tolerances) lives in code instead of CLI flags; per-run flags (`--force`,
`--verbose`, `--json`) ride `sys.argv` and keep working unchanged.

The `@dxf` decorator is the sibling for drawings (same machinery, gen_dxf's
return-a-drawing contract, no render package). `.implicit.js` is out of scope.

## Decorator semantics (settled)

- **Decoration-time execution.** `@step` registers the function; when the
  defining module is `__main__`, it runs the pipeline right there — an
  ordinary decorator, no atexit/excepthook machinery, so exceptions and exit
  codes are plain Python. Consequence (the one documented rule): everything
  the model needs must be defined ABOVE the decorated function. The natural
  file shape puts the model last; violations fail immediately with NameError.
- **Import never builds.** Importing a model module only registers. This keeps
  composition, tests, and the warm worker's re-import safe.
- **Transparent callable.** Calling `bracket()` returns the shape and does
  nothing else. Composition imports the child module and calls the function —
  now via ordinary `import bracket` since scripts are real modules (see naming).
- **Registry replaces the magic name.** The registered function is the handle
  snapshot `--params` sweeps and the incremental param-edit machinery re-invoke.
- **Order of operations on a direct run:** freshness gate first (no CAD import
  has resolved yet — see lazy imports), then warm-daemon proxy (the worker
  imports the module as a normal module and calls the registered function), or
  in-process cold fallback when no daemon is available.
- **Collision guard.** A build refuses to overwrite an artifact whose package
  descriptor records a DIFFERENT `sourcePath` (override with `--force`), so
  artifact ownership stays explicit once filenames stop enforcing uniqueness.

## Lazy imports: `from cadgen import build123d as bd`

`cadgen.build123d` is a PEP 562 lazy module proxy: attribute access triggers
the real import once and returns the REAL objects thereafter. Measured on this
machine: cold `import build123d` = 2.45s; bare interpreter = 24ms.

- Zero semantic edges: `bd.Box` IS the real class after first touch —
  isinstance, subclassing, `except`, identity, context managers all genuine.
- The invoker never pays the 2.45s on the warm path (`bd.*` resolves only in
  the worker) and never pays it at all on a skipped (current) build — even
  daemonless no-op re-runs stay ~0.2s because the gate fires before any
  attribute touch.
- `from cadgen.build123d import Box` is necessarily EAGER (a from-import must
  bind the object), so `bd.` attribute style is the canonical idiom, like
  `np.`. A per-name lazy-proxy tier (making from-imports lazy via
  `__call__`/`__instancecheck__`/`__mro_entries__` forwarding) is possible and
  prior-friendly for agents, but carries two unfixable edges — proxies in
  `except` clauses TypeError, and `type(x) is Box` is False forever — so it is
  deliberately DEFERRED until style-slip friction is observed in practice.
- The wrapper is a TRANSPARENT re-export: same names, same signatures, never
  "improved" — agents' build123d knowledge must transfer 1:1. A generated
  `.pyi` stub re-exports names for type checkers/IDEs.
- Raw `import build123d` keeps working (correct, just ~2.5s cold in the
  invoker); the decorator prints a one-line advisory pointing at the `bd.`
  idiom when it detects eager OCP in a cold `__main__` process.
- Policy test: `import cadgen` stays light (bounded time, no OCP in
  sys.modules) so the framework itself never becomes the cold cost.

## Performance (vs the gen CLI today)

| scenario                     | today (shim+daemon) | library-first |
|------------------------------|---------------------|---------------|
| warm no-op re-run            | ~0.1–0.3s           | ~0.2s (parity) |
| warm real build              | pipeline cost       | identical      |
| cold real build              | pipeline cost + OCP | identical      |
| daemonless no-op re-run      | ~2.5s (cold import) | ~0.2s (BETTER: gate precedes import resolution) |

Everything expensive — daemon, locks, progress records, closure capture, op
cache, component store, tessellation cache — is the same pipeline invoked from
a different entrypoint. Double-import semantics: on a warm proxy the module
body executes in both the invoker and the worker; module bodies must only
DEFINE (which the lazy-import + decoration-time design already encourages).

## Discovery and naming: the `.step.py` / `.dxf.py` convention retires

Scripts become plain `.py` files (importable modules — the double suffix never
was). The script→artifact link is declared in code (`write=`, defaulting to
`<stem>.step` beside the script). The artifact→source link moves to what the
package descriptor already records (`sourceKind`/`sourcePath`/`sourceHash`):

- **Generated-vs-imported classification** (the digest gate) re-keys from
  same-stem-file-exists to descriptor provenance, in BOTH the Python side and
  the viewer's `artifactStatus.mjs` twin (contract-sync tests fence them).
  A bare artifact with no package defaults to importable; its first scripted
  build stamps the truth.
- **The viewer catalog becomes artifacts-only.** Artifactless scripts no
  longer appear as buildable entries (consistent with the static-viewer
  doctrine); reveal-source and regenerate hints ("run `python <sourcePath>`")
  come from the descriptor. The scanner sheds source sniffing entirely, and
  the same-stem shadowing traps die with the convention.
- **Params sidecars** live with the code and are resolved via descriptor
  provenance rather than same-stem pairing.
- CLIs that take a model target (snapshot, export) accept either the artifact
  (descriptor-driven, preferred) or a script path (registry-driven). Nothing
  ever sniffs arbitrary `.py` files.

## CLI fate

- The gen CLI's GENERATOR arm is deleted. Its imported-raw-STEP arm survives
  (there is no script to run for a vendor STEP) and is renamed
  (`scripts/import` / `cadgen import`).
- snapshot/export/inspect remain CLIs — they operate on models, not authored
  code.

## Backwards compatibility: none, with teaching errors

No compat shim. Pre-1.0 is the last cheap moment; dual contracts double every
surface (two discovery rules, two doc sets, two status classifications in two
languages); the magic-name mechanism is the thing being deleted. Instead:

- Cheap static detection of a legacy `gen_step` module (and of legacy
  `.step.py`/`.dxf.py` naming) produces a HARD, ACTIONABLE error from both the
  status path and direct execution: "legacy generator — see
  skills/cad/references/migrating-generators.md" with the one-line
  before/after. Agents migrate on contact, from the error message.
- The migration doc ships the AST codemod (wrap `gen_step` → decorator,
  rewrite `from build123d import X` → `bd.` style, rename to plain `.py`).
- The repo corpus migrates in one gated pass (deferred — see below), verified
  by the strongest check available: package content hashes byte-identical
  pre/post migration for every model.

## Project structure: flexible core, opinionated skill

**cadgen stays unopinionated**: `write=` defaults to the script's sibling and
accepts any path; no layout detection, no routing, no structure hints in core.
**The `cad` skill stays scoped to single-file generation** and cross-references
the structure skill.

**A new standalone `skills/cad-project` skill** carries the opinionated
standard for bigger projects (documentation + scaffold template, no runtime
code):

```
<project>/
  src/            # authored: one model per file (stem = artifact stem),
                  # _underscore.py helpers, params sidecars
  imports/        # authored inputs: vendor/foreign STEPs (committed)
  STEP/  DXF/     # primary artifacts + their __cadgen__/ packages
  STL/ GLB/ 3MF/  # derived exports
  PNG/ GIF/       # snapshots/animations
```

One mechanical rule: generated files go to the capitalized folder of their
extension; authored files live in `src/` (or `imports/`). Precedent already in
the repo (`models/renders/juno/STEP/`).

**Commit policy** (the skill's, adopted by `models/` at migration): format
folders are gitignored — code-only by default, since builds are gated, cached,
and deterministic enough to regenerate on demand. Committed exceptions, made
structural: `imports/` (no code can regenerate a vendor STEP) and pinned
fixtures (determinism is per-kernel-version; anything asserted byte-for-byte
by tests/parity suites keeps its artifact in git via LFS). Doctrinal
amendment, stated openly: detached-outputs still governs local behavior (the
viewer renders what exists; nothing rebuilds behind the user), but across
clones the effective shared truth becomes code + regeneration except for
imports and fixtures.

**Flagged decision (Phase 0):** how the skill's layout stays mechanical
rather than per-call boilerplate —
(a) pure convention: the skill teaches `write="../STEP/x.step"` via scaffolded
examples; or
(b) a GENERIC hook in cadgen: the decorator consults an optional per-project
marker (`cadproject.toml` declaring output routing); no marker → sibling
default. The mechanism ships with zero opinion; the skill's opinion is the
scaffolded marker. Current lean: (b) — model scripts stay clean (`@step()`
with no path) and the layout is a project-level, inspectable choice.

## Agent-comprehension notes

Semantic knowledge transfers 1:1 (transparent re-export; nothing renamed).
The one bounded risk is style slips toward bare `Box(...)` from training
priors — mitigated by the migrated corpus as in-context examples (dominant
signal), instant self-explanatory NameError, the skill template, and the
decorator's advisory hints. The deferred from-import proxy tier is the
prior-friendliest form and stays in reserve.

## Phases

0. **This document** — settle decorator semantics, lazy-import story,
   discovery re-keying, structure split, the marker-file decision.
1. **Library core** — `cadgen.step`/`cadgen.dxf` + registry + lazy
   `cadgen.build123d` (+ `.pyi` stub); static decorator detection replaces
   `gen_step` name detection in catalog/generation_spec.
2. **Machinery rewire** — warm-daemon proxy for direct runs; param overrides
   through the registry; descriptor-provenance classification in Python and
   the JS status twin; artifacts-only catalog; hint strings.
3. **CLI cutover** — delete the gen generator arm; rename the import arm;
   teaching errors for legacy name/naming; migration doc + codemod.
4. **Skills** — `cad` skill rewritten for decorator usage; new `cad-project`
   skill (structure, commit policy, scaffold); docs sweep.
5. **Pilot migration (decided 2026-08-29): a SMALL representative subset, not
   the corpus.** Phase 3's hard deprecation proceeds with only the pilot
   migrated. Pick ~3–5 projects covering the contract surface — a single
   part, a multi-occurrence assembly, a DXF drawing, a params-sidecar model,
   and (if feasible) a composed/imported-child model — migrate them to the
   decorator + cad-project structure, hash-verify their packages pre/post,
   and use them as the living examples the skills reference. Inline test
   fixtures (BOX_GENERATOR-style strings) migrate with phase 3.

   Consequence, accepted deliberately: the REST of `models/` becomes
   regeneration-blocked (its `.step.py` scripts hit the teaching error) while
   its committed artifacts/packages keep rendering everywhere — artifacts are
   the truth; only re-running old generators is gated on migration. The
   corpus-wide codemod + layout policy test are a LATER, separately-scheduled
   job.

## Open decisions

- Marker-file hook (b) vs pure convention (a) for cad-project output routing.
- Exact rename for the imported-STEP build command (`scripts/import`?).
- Whether the from-import proxy tier ever ships (only on observed friction).
- ~~Phase 3 / corpus-migration sequencing~~ — decided: phase 3 lands with the
  pilot subset only; full corpus migration is deferred work.
