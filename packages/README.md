# Packages

Libraries and distributions. Applications live in `apps/`.

- `cadgen/` — the published distribution: the Python engine plus the built
  JS runtimes it executes. The design laws live in its README.
- `cadgen-js/` — the shared JS source between cadgen's rendering and its
  clients (the viewer, the docs app). Framework-free by law.

Each package's README carries its PURPOSE / MAY DEPEND ON / DEPENDED ON BY
boundary and the laws that live there. New shared code goes in the package
whose boundary admits it — never in an app, never duplicated.
