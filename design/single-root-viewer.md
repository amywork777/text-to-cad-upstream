# One root directory per Viewer instance

Status: planned, not started. Target branch: `release/0.5.0`.

## The invariant

**A Viewer instance serves exactly one directory, fixed at startup. The page is
always at `/`. `?file=` is the only thing that varies, and it is always relative
to that root.**

```text
http://127.0.0.1:3245/?file=mechanisms/lift_table.step.py
```

Everything below follows from that one sentence. If a change does not serve it,
it is not part of this work.

## Why

Today the URL **path** is an absolute filesystem directory, exactly as in a
`file://` URL, and `?file=` is relative to it. One instance can therefore serve
any folder on the machine. That flexibility is the source of a disproportionate
amount of code:

- `viewer/paths.py` (71 lines) exists only to translate a URL path to a
  filesystem path and back, because a Windows absolute path carries a drive
  (`D:\models`) while a URL path must start with `/`, so the wire form is
  `/D:/models`. `os.path.abspath("/D:/models")` yields `C:\D:\models` and
  `os.path.join(dist, "D:/models")` yields `D:\models`. Both silently produce a
  path nobody asked for. That is issue #211.
- `tests/python/packages/cadgen/viewer/test_windows_drive_paths.py` (374 lines)
  exists to pin that translation.
- `_serve_dist` cannot use "has an extension" as its static-asset test, because
  `/Users/j/v0.4/models` is a directory containing a dot. It has to special-case
  the bundle's own `/assets/` prefix and strip drive letters before joining.
- The client carries two root concepts at once, `directoryRoot` (the server's
  startup directory) and `rootDir` (the per-request root off the URL path), plus
  a reconciliation layer between them: `stripViewerRootDirPrefix`,
  `rootRelativePathFromDirectoryRelativePath`,
  `directoryPathIsInsideViewerRoot`.

Pinning the root deletes that whole category. There is no URL-to-filesystem
translation left to get wrong, on any platform.

### It also closes a real hole

`backend.asset_path_for_file_ref` gates its containment check behind
`active = resolved_root or (self.resolve_root(root_dir) if root_dir else None)`
and `if active:`. When a request carries no `dir=`, `active` is `None` and the
check **does not run at all**. Containment today is effectively opt-in by the
caller. With a root fixed at startup there is always an active root, so the
check becomes unconditional. Do not treat this as a bonus to bolt on later; it
falls out of the design and must be asserted by a test.

## The tradeoff, stated plainly

One instance can no longer serve a second folder. To open a different root you
start another instance on another port. Accept this. It is the point of the
change, and the registry added in `6614b76d` already makes concurrent instances
manageable: `cadgen viewer list` shows them, `cadgen viewer stop --port <n>`
ends one, and a port collision already names the holder rather than silently
reusing it.

## No backwards compatibility

Delete the old paths outright. Do **not** add fallbacks, aliases, deprecation
shims, or "accept the old form too" branches. Specifically:

- `?dir=` is removed, not deprecated. No handler reads it.
- A URL path other than `/` and the bundle's own asset paths is **not**
  reinterpreted as a directory. Serve the SPA or 404, per Phase 3.
- Old-style links stop working. That is intended.

## New contract

**CLI.** `cadgen viewer [--root <dir>] [--host H] [--port N]`. `--root` defaults
to the process cwd, which is what `_Ctx.directory_root` already does today, so
the default behaviour is unchanged. Resolve it once with `os.path.abspath`, and
fail to start with a clear message if it is not an existing directory. A viewer
pointed at a missing root should never boot and then 404 every request.

**URL.** Origin plus `/`, with `?file=` relative to the root. `viewer_url()`
loses its `directory` parameter and returns `http://{host}:{port}/`, optionally
with `?file=`.

**Server info.** `/__cad/server` reports one root. Drop `rootDir` from the
payload; keep `directoryRoot` as the single name and make it the resolved root.
Do not ship both names.

---

## Phase 1: the server pins one root

Files: `packages/cadgen/src/cadgen/viewer/server.py`,
`packages/cadgen/src/cadgen/viewer/backend.py`,
`packages/cadgen/src/cadgen/viewer/start_viewer.py`

1. Add `--root` to the parser in `start_viewer.py` (near the existing `--host` /
   `--port` at lines 121-123) and thread it to the backend spawn the same way
   `--dist` is threaded in `spawn_backend`.
2. In `server.py`, set `_Ctx.directory_root` from the new argument instead of
   bare `os.getcwd()` (currently at the top of `main`, around line 488). Validate
   it is a directory; print and `return 1` if not.
3. Delete every `root_dir = q.get("dir", "")`. There are roughly ten, at lines
   226, 229, 315, 395, 410, 428, 457 and their neighbours. Each call that took
   `root_dir=` now uses the single startup root.
4. In `backend.py`, change `resolve_root` to take no request argument and return
   the resolved startup root. Delete the `requested or os.getcwd()` fallback at
   line 176.
5. In `asset_path_for_file_ref` and `contained_path_for_file_ref`, drop the
   `root_dir` parameter and the `if active:` gate. The root is always present;
   the containment check always runs.
6. Remove `rootDir` from `_server_info` (line 138).

**Verify:** `./.venv/bin/python -m unittest tests.python.packages.cadgen.viewer.test_registry`
and the viewer suite. Then start a viewer and confirm `?dir=` is ignored:

```bash
curl -s "http://127.0.0.1:3299/__cad/server" | python3 -m json.tool
```

Add a test asserting a `file=` outside the root returns 403 **with no `dir=` in
the request**. That test fails on today's code, which is the proof the hole was
real.

## Phase 2: delete the URL/filesystem translation

1. Delete `packages/cadgen/src/cadgen/viewer/paths.py`.
2. Delete `tests/python/packages/cadgen/viewer/test_windows_drive_paths.py`.
3. Remove `url_path_from_filesystem_path` usage from `start_viewer.viewer_url`
   and drop its `directory` parameter.
4. `git grep -n "viewer.paths\|url_path_as_relative\|url_path_from_filesystem_path"`
   must return nothing outside deleted files.

Do not preserve any part of `paths.py` "just in case". Its entire reason for
existing is the thing being removed.

## Phase 3: `_serve_dist` becomes an ordinary static server

File: `packages/cadgen/src/cadgen/viewer/server.py`, lines 330-378.

Only `/` and the bundle's own assets are valid now. Serve the file if it exists
under `dist_root`, otherwise serve `index.html` for `/`, otherwise 404. Delete
the drive-stripping join and the comment paragraph explaining why extensions
cannot be the static-asset test. Keep the containment check on the resolved
path; it is cheap and still correct.

## Phase 4: the client drops the second root concept

Files: `viewer/src/client/workbench/pathPresentation.js` (116 lines),
`viewer/src/client/workbench/fileAccessAssets.js` (220 lines),
`viewer/src/client/components/CadWorkspace.js:1563`,
`viewer/src/client/components/workbench/CadRenderPane.js:407`, and their tests.

There are 13 non-test references to `rootDir` in `viewer/src/client`. All go.

1. Delete `stripViewerRootDirPrefix`, `directoryPathIsInsideViewerRoot`, and
   `rootRelativePathFromDirectoryRelativePath`.
2. Replace `viewerServerInfo?.rootPath || viewerServerInfo?.directoryRoot` with
   the single `viewerServerInfo.directoryRoot`.
3. Stop emitting `dir=` anywhere. Check
   `viewer/src/client/components/workbench/hooks/packageAssetUrl.js`, whose
   header comment documents the old `?file=…&dir=…` shape.
4. Update the fixtures in `fileMetadata.test.js`, `fileStatusItems.test.js`, and
   `fileAccessAssets.test.js`, which all declare a `directoryRoot` and some a
   `rootDir`.

`viewer/scripts/directoryRoot.mjs` (33 lines) is a **different** thing: it picks
the dev server's root for `vite.config.mjs` and `start-viewer.mjs`. Keep it, but
make it feed the new `--root`.

## Phase 5: the registry learns what each instance serves

Files: `packages/cadgen/src/cadgen/viewer/registry.py`,
`packages/cadgen/src/cadgen/cli/viewer_list.py`

The registry docstring currently says instances "do not differ by what they
serve -- they differ by WHICH CHECKOUT'S CODE they run". **After this change
that sentence is false**, and it is load-bearing prose, not decoration.

1. Add `"root"` to the `register()` payload beside `packageDir`.
2. Print it in `viewer_list.format_entry`, on its own line under the URL.
3. Rewrite both module docstrings so they describe one-root instances.

This is the smallest phase and the easiest to skip. Do not skip it: `list`
becomes the only way to see which instance serves which folder, so it is now
load-bearing for the workflow, not a nicety.

## Phase 6: documentation

`AGENTS.md` and `skills/cad-viewer/SKILL.md` both document the URL shape,
including the Windows `.../3245/D:/project/models` form. `AGENTS.md` also says
"The Viewer is not started against a directory — it opens whatever a URL names,
so one instance serves any folder", which inverts under this change. Rewrite
both, and check `skills/cad-viewer/references/viewer-features.md`.

## Phase 7: regenerate and verify

```bash
npm --prefix viewer run build
scripts/bundle/bundle.sh                 # regenerates the packaged runtime
scripts/bundle/bundle.sh --check         # must be clean
scripts/dev/setup-symlinks.sh --check    # bundling has broken this before
scripts/test/test.sh
```

Then the end-to-end check, which is the one that actually proves it:

```bash
scripts/test/test-viewer-launch.sh
```

## Traps

- **Bundling breaks the worktree symlink layout.** After `bundle.sh`, rerun
  `scripts/dev/setup-symlinks.sh`, delete `viewer/node_modules/.vite`, and
  restart the dev server. A stale Vite transform cache survives HMR and a hard
  reload, so you will edit a file, see no change, and chase the wrong bug.
- **Do not verify a Viewer link by curling `/__cad/asset`.** That route serves
  raw files; a generated entry's render package comes from a different route, so
  probing it returns 404 whether or not anything is wrong. Load the page.
- **Never probe the export or reveal routes.** They open native save dialogs and
  Finder windows on the developer's machine.
- **`test_snapshot_viewer_theme_parity.py` reads JS source paths directly.** If
  you move client files, check it still resolves.
- **Windows CI is real on this branch and it will catch you.** `Test (Windows)`
  runs the full Python suite. Deleting `paths.py` is safe only because the URL
  no longer carries a drive letter; if any code path still builds a filesystem
  path from a URL path, Windows finds it and Linux does not.
- **Do not stop a Viewer you did not start.** Other checkouts may have instances
  running on this machine.

## Definition of done

Baselines below were measured at `d2988ec0`, the head this plan was written
against. Every line reference in this document was checked against that commit.
If a count already reads 0 before you start, the grep is wrong, not the code.

| Check | Now | Done |
| --- | --- | --- |
| `git grep -c '"dir"' packages/cadgen/src/cadgen/viewer/` | 13 | 0 |
| `git grep -c "rootDir" viewer/src packages/cadgen/src` | 21 | 0 |
| `packages/cadgen/src/cadgen/viewer/paths.py` | exists | deleted |
| `tests/python/packages/cadgen/viewer/test_windows_drive_paths.py` | 374 lines | deleted |

Plus:

- A `file=` escaping the root returns 403 on a request carrying no `dir=`. Write
  this test first and watch it fail on today's code; that failure is the proof
  the containment hole was real.
- `cadgen viewer list` shows each instance's root.
- `Test (Linux)`, `Test (Windows)`, and `Version Check` are green.
