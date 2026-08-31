# AGENTS.md

This repo is a workbench for CAD-related agent skills. Treat `skills/` as the
product and `models/` as the shared fixture/artifact area.

## Branch And Layout First

Before changing code, branch from `develop`, not `main`; PRs should target `develop`.
Do not start development work from `main`. The `develop` branch intentionally uses
symlinks across generated runtime and viewer-local package paths. When a path is
symlinked, follow the link and edit the source target.
Use `main` as the production clone/release branch only. `main` is publish-only:
do not open PRs to `main` or push it directly.

## Release Workflow

Do not bump the canonical release version in `VERSION` during
normal development work. Ship releases only through the single `Release`
GitHub Actions workflow, which handles the version bump, release PR, publish
commit to `main`, `cadgen` PyPI publish, docs deploy, semver tag, and GitHub
Release in one run.

When asked to publish, make, or ship a release, dispatch `Release` with its
defaults: build from `develop` (`base_branch=develop`), publish to `main`
(`target_branch=main`), and publish the GitHub Release (`publish=true`, not a
draft). Never pick the semver bump yourself: if the request does not name
patch, minor, major, or an exact version, ask which one before dispatching.
Use `target_branch=build-test` only when the user explicitly asks to test
CI/CD or build-pipeline changes — never by default and never as part of a
requested release, and pair it with `bump=none` so a rehearsal does not consume
a version number. `bump=none` publishes `base_branch` as it stands and is also
how you resume a failed publish; it is never a release setting.

The standalone `Deploy Docs` workflow redeploys the docs site without running a
release. It deploys a source ref (defaulting to `develop`), never `main`: the
publish tree drops `docs/` and `packages/`, which the docs app builds against.
The CAD Viewer is a local-filesystem app with no hosted deployment: the
cad-viewer skill bundles the built client + JS server, and each release mirrors
`viewer/` into the standalone `earthtojake/cad-viewer` repo through the
`Sync CAD Viewer Repo` workflow (which `Release` calls after publishing and which
can also be dispatched on its own; it reads the release SOURCE commit, because
`main` carries only what installs). `Deploy Docs` also reads the release SOURCE
commit.
`main` is publish-only; pushing `develop` runs tests but
never publishes. See the Releases section in `CONTRIBUTING.md` for the full
flow, CI/CD-testing and resume options, and local/manual fallbacks.

## Repo Map

- `skills/`: agent skills and their references/scripts.
- `.claude-plugin/`, `.codex-plugin/`: agent plugin manifests. The repository
  root is the plugin package; its skills are `skills/` directly.
- `models/`: sample and durable CAD/robot-description fixtures.
- `viewer/`: editable CAD Viewer source app.
- `packages/cadjs`: shared JS CAD/render/runtime code, UI-framework agnostic.
- `packages/cadgen`: the published distribution — STEP/GLB/topology generation,
  the skill CLI parsers, the CAD Viewer backend + client, and the Node/browser
  runtimes it executes.
- `docs/`: documentation site.
- `tests/`: root-owned test suites for skills, packages, viewer services, and
  repo-wide policy.
- `scripts/`: durable repo commands grouped by purpose.

## Repo Rules

- Read `packages/cadgen/DESIGN.md` — the three cadgen design laws
  (generated-file independence, cache purity, decorator/function/CLI sync) —
  before changing generation, rendering, storage, or public interfaces.

- Keep root guidance short. Put domain workflows, CLI details, and validation
  policy in the relevant `skills/<skill>/SKILL.md` or `references/` file.
- Keep relevant Markdown docs current when changing behavior, commands, or repo
  layout, but do not bloat `AGENTS.md`; use it only for durable repo-level
  rules and pointers.
- Read `CONTRIBUTING.md` before committing, rebasing, resolving generated-file
  conflicts, or bumping release versions.
- Keep the primary local `develop` checkout in symlink layout with
  `scripts/dev/setup-symlinks.sh`. Do not auto-repair that layout from
  Codex or Claude Code startup hooks in linked worktrees.
- A skill must not import another skill, a `skills/` root module, or a
  repository-root module, and must not add `skills/`, the repository root, or a
  sibling skill directory to `sys.path`, `PYTHONPATH`, `NODE_PATH`, or any other
  runtime lookup path. Skills are independent of each other, not of everything.
- Shared runtime comes from the **`cadgen` distribution**, named in each skill's
  `requirements.txt` — unpinned on `develop` so the editable install in
  `requirements-dev.txt` satisfies it, pinned to the release at publish. Skills do
  not vendor it: a skill script is a thin entrypoint whose parser and behaviour
  live in `cadgen.cli`, and which fails with the `pip install -r requirements.txt`
  hint when cadgen is missing. cadgen carries the JavaScript it executes too (Node
  builders, the snapshot browser bundle, the CAD Viewer client), so a skill ships
  no runtime of its own.
- Edit the source reached by the `develop` symlink layout first, then regenerate
  explicit derived outputs when a production-output task requires it.
- Write all test, sample, permanent, and generated CAD/robot-description
  artifacts under `models/`, including STEP/STP, STL, GLB, DXF, URDF, SRDF,
  and SDF outputs. Do not create ad hoc artifact directories elsewhere.
- Reserve `scripts/` for durable repo commands. Do not write temporary,
  one-off, or local-only helper scripts there; use `tmp/` or `/tmp` instead.
- Development symlinks mark generated or copied paths. If a file is under a
  symlinked runtime or viewer package path, edit the symlink target/source path
  instead of treating the copy as independent.
- When source changes affect generated runtimes, refresh or check them with the
  master bundle wrapper, `scripts/bundle/bundle.sh`. Use lower-level bundle
  scripts only when debugging the wrapper itself.
- Never let a symlink reach the published tree. Agent installers disagree about
  symlinks and one loses data silently: the Skills CLI dereferences them, Claude
  Code preserves them, and Codex `plugin add` drops them with no error, shipping
  a skill with missing files. `scripts/github-workflows/check-builds.sh` enforces
  this; do not relax it.
- `viewer/` is the whole CAD Viewer app: the React client (`src/`) AND its
  pure-JS backend (`server/`, dependency-free Node). It is a standalone app,
  separate from cadgen: the cad-viewer skill bundles the built client + server
  at `skills/cad-viewer/scripts/viewer` (a dev symlink here; materialized by
  `bundle-cad-viewer.sh` for publish), and each release mirrors `viewer/` to the
  standalone `earthtojake/cad-viewer` repo. The backend's render path runs no
  Python; importing a foreign STEP spawns `cadgen step build` (a soft dependency —
  absent cadgen, viewing still works). Keep repo-level tooling in `scripts/`,
  not under `viewer/`.
- `packages/cadjs` must stay reusable/non-React; app UI and workflow state
  belong in `viewer/`. It holds the shared CAD render/runtime code: one package,
  one copy of each shared primitive.
- `packages/cadgen` is the whole distribution, not just the Python: artifact
  generation, the CLI parsers behind every skill command (`cadgen/cli`), the warm
  build daemon (`cadgen/daemon`), and
  the JS/SPA assets it executes (`cadgen/_runtime`, built by
  `scripts/bundle/skills/bundle-cadgen-runtime.sh`). Skills consume it as an
  installed distribution.
- Create lightweight shared Python packages under `packages/` when a helper
  should not inherit heavier package dependencies.
- Use path-targeted search, validation, and `git status`; avoid broad scans over
  generated CAD/LFS artifacts unless the task requires them.
- Treat `VERSION` as the canonical release version. Do not hand-edit duplicate
  package, plugin, lockfile, or Python `pyproject.toml` versions; release
  preparation and `scripts/bundle/bundle.sh` stamp them from the canonical
  version.

## Environments

- Prefer `./.venv/bin/python` for CAD Python work.
- Keep new branch checkouts and git worktrees lightweight by default. Do not
  copy `.venv/` or `models/` through `.worktreeinclude`; recreate `.venv/`
  inside the worktree only when Python dependencies are needed for the workflow.
- In Codex or Claude Code worktrees, prefer the skill instructions and scripts
  under the current worktree's `skills/` directory over globally installed
  skill symlinks from another checkout.
- If a worktree explicitly needs the development symlink layout, run
  `scripts/dev/setup-symlinks.sh --check` and then
  `scripts/dev/setup-symlinks.sh` intentionally in that worktree.
- Hydrate `models/` only when the user asks for it or when the task targets
  specific files under `models/`. In a new worktree, make the relevant model
  paths real before using them, preferring the local Git LFS cache with
  `git lfs checkout <path>` or `git lfs checkout models`. Download missing LFS
  objects only when explicitly requested or required after confirming the local
  cache is missing them.
- Install dependencies only for the workflow being changed.
- Do not commit `.venv/`, `node_modules/`, caches, `tmp/`, local credentials, or
  printer config.

## Checks

Run the smallest path-targeted check that covers the change. Use broad wrappers
when touching shared surfaces or before handoff:

- Code tests: `scripts/test/test.sh`
  - In GitHub Actions, `test.yml` checks the canonical release version in a
    separate job so code tests still run when version metadata is wrong; its
    test job verifies the `develop` symlink layout, checks generated outputs
    against their sources, bundles temporary production outputs, and runs docs
    and code tests against that bundle. `main` writes are validated by the
    `Release` workflow's publish job; GitHub branch settings should block PRs
    and direct pushes to `main`.
- Focused test runners: `scripts/test/test-js.sh`,
  `scripts/test/test-docs.sh`, `scripts/test/test-python.sh`,
  `scripts/test/test-global.sh`
- Development symlink layout: `scripts/dev/setup-symlinks.sh --check`
- Canonical release version: `scripts/release/check-version.sh`
- Generated runtime freshness: `scripts/bundle/bundle.sh --check`
- CAD Viewer or `packages/cadjs`:
  `npm --prefix packages/cadjs test`,
  `npm --prefix viewer run test`, `npm --prefix viewer run build`
- Docs site: `npm --prefix docs run check`
- Targeted Python tests: `./.venv/bin/python -m unittest <changed test paths>`

When a task intentionally writes production outputs locally, run
`scripts/bundle/bundle.sh`, rerun `scripts/bundle/bundle.sh --check`, and restore
the development symlink layout afterward if you are continuing on `develop`.

## CAD Viewer

A Viewer instance serves ONE directory, fixed when it starts. The page is always the
bare origin and `?file=` selects an artifact inside that root:

```text
http://127.0.0.1:3245/?file=path/relative/to/the/served/root
```

Launch it against a directory with `--root` (defaults to the current one) and read
the URL it prints — launching is unconditional:

```bash
node viewer/server/main.mjs --root <absolute dir> --host 127.0.0.1 --json
```

A live instance already serving that realpath at this version is REUSED
(`action:"reused"`); otherwise the server binds the first free port from `3245`
upward (`action:"started"`). `--new` forces a fresh instance (use it when testing
server-code changes from a checkout — a reused instance runs the code it started
with); an explicit `--port` is strict and exits 1 when taken. To review a second
directory, just launch again with that root. `node viewer/server/main.mjs list`
shows every running instance with the root it serves and the checkout its code came
from; `... stop --port <n>` ends one.

When reviewing repo fixtures, start the Viewer with the repo `models/` directory as
its root and keep permanent or generated CAD/robot-description files there so the
catalog and artifacts stay in one place. Pass an absolute `--root`: the Viewer runs
from an arbitrary working directory, so a relative one resolves against the wrong
place. Do not stop another Viewer unless the user asks.

Editing `viewer/` or `packages/cadjs` source and not seeing the change? Vite's
server-side transform cache can outlive both HMR and a hard reload — the browser
keeps serving the old module while the file on disk is already correct. Restart
the dev server and delete `viewer/node_modules/.vite`.

### Dev by default, prod only for e2e

Iterate with the **dev** server — Vite serves the client from source with HMR, so
your `viewer/` and `packages/cadjs` edits show up live:

```bash
npm --prefix viewer run dev -- --host 127.0.0.1
# then open http://127.0.0.1:5173/?file=<path relative to the served root>
```

Use the **prod** path only for end-to-end tests against the shipped bundle, or
when explicitly asked to test prod. It serves the built `dist/` via the JS server
(the `cad-viewer` skill's launch command), so build first:

```bash
npm --prefix viewer run build
npm --prefix viewer run start -- --host 127.0.0.1 --json
# then open the URL from the printed {url,port,action} line
```

### Ports

Dev lives on Vite's port (`5173`), is strict (taken → pick another with `--port`),
and never enters the instance registry. The bundled launcher (`start` /
`main.mjs`) needs no port at all: it reuses or rolls and prints the real URL.

Packaged Viewer runtime and handoff details live in the `cad-viewer` skill.
Treat packaged Viewer checks as generated-output checks via the master bundle
wrapper unless you are debugging a lower-level script.

### Starting the Viewer from a lightweight worktree

The backend is pure JS (`viewer/server`), so a worktree needs only Node — plus a
cadgen-importable interpreter for builds, handed down via env:

```bash
CADGEN_PYTHON=<main>/.venv/bin/python \
PYTHONPATH=<worktree>/packages/cadgen/src \
node <worktree>/viewer/server/main.mjs \
  --root <worktree>/models --dist <worktree>/viewer/dist --host 127.0.0.1 --json
```

`--dist` points at the client you are editing; `--root` names the directory this
instance serves, so point it at the worktree rather than relying on the shell's
cwd. Building that
client needs the worktree's `node_modules`, which worktrees deliberately do not carry —
link them from the primary checkout first:

```bash
ln -s <main>/viewer/node_modules viewer/node_modules
mkdir -p packages/cadjs/node_modules
ln -s <main>/packages/cadjs/node_modules/three        packages/cadjs/node_modules/three
ln -s <main>/docs/node_modules/meshoptimizer          packages/cadjs/node_modules/meshoptimizer
npm --prefix viewer run build
```

No port juggling is needed: reuse keys on realpath(root) × version, so a Viewer
from another checkout (different root) can never be handed back for this worktree —
the launcher just rolls to a free port and prints the real URL.

Two behaviours worth knowing before you conclude a model is broken:

- **The catalog scan skips dot-directories.** A buildable entry under `.review/`
  or any other dotted path never appears in a scan of the served root, and the
  Viewer reports that the file does not exist. Pointing `--root` straight at the
  dotted directory does not help either: entries below the root are filtered on the
  same rule. Keep buildable entries out of dotted directories.
- **Verify a Viewer link by loading the page**, not by curling `/__cad/asset`.
  That route serves raw files; a generated entry's render package is served by a
  different route, so probing it returns 404 whether or not anything is wrong.

## Git And LFS

CAD exchange files, generated render/topology assets, and `assets/**` may be
LFS-tracked. Never disable LFS filters for `git add`, commits, or other
object-writing operations. Local hooks live in `.githooks` and
delegate build checks through `scripts/git-hooks/pre-commit`.
