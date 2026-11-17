# vendor

npm packages the repository installs from a file, until they are published.

## `draftwright-specify-ui-0.1.0.tgz`

[`@draftwright/specify-ui`](https://github.com/pzfreo/specify-ui) 0.1.0 (Apache-2.0, Betwixt Limited
trading as Draftwright): Specify's STEP diff (and review) components, which `@cad/ui`'s Compare uses
(`packages/ui/src/compare/`). It is not on npm yet, and a GitHub dependency installs without its
`dist/` (the package builds it in `prepack`, which npm does not run for a git dependency), so the
built package is kept here.

- Built with `npm ci && npm pack` from `pzfreo/specify-ui` at
  `a045e1113d16770e73bc20a3634ec169f77f3d38` (main, 2026-11-17).
- One change to its `package.json`: the `three` peer range is `>=0.184.0 <0.188.0` (the release says
  `<0.187.0`), since text-to-cad is on three 0.187.0 and npm cannot override a peer range. Nothing
  else in it is changed.
- The root `package.json` overrides `three-cad-viewer`'s exact `three` 0.184.0 with 0.187.0, so a page
  has one three.js.
- sha256 `6edb8dc8fd37074a504aab3fc4ee09989ab8df651309988e99fd484420874322`.

Once the package is on npm with a range that takes three 0.187, depend on it by version
(`packages/ui/package.json`), drop the override if `three-cad-viewer` allows it, and delete this file
and the tarball.
