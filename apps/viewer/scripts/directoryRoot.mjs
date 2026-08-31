import path from "node:path";

// By path, not by the bare "cadgen-js" specifier. This module runs from the shipped CAD Viewer
// runtime, which vendors packages/cadgen-js but has no node_modules to resolve a package name
// through. viewer/packages/cadgen-js is a symlink in development and a real directory once
// bundled, so the same relative path works in both.
import { pathIsInside } from "../packages/cadgen-js/src/lib/pathUtils.mjs";

export function resolveDirectoryRoot({
  directoryRoot = "",
  env = process.env,
  cwd = process.cwd(),
  appRoot = "",
  defaultDirectoryRoot = "",
} = {}) {
  const explicitRoot = directoryRoot || "";
  if (explicitRoot) {
    return path.resolve(cwd, explicitRoot);
  }

  const resolvedAppRoot = appRoot ? path.resolve(appRoot) : "";
  for (const candidate of [env.INIT_CWD, cwd]) {
    if (!candidate) {
      continue;
    }
    const resolvedCandidate = path.resolve(candidate);
    if (!resolvedAppRoot || (resolvedCandidate !== resolvedAppRoot && !pathIsInside(resolvedCandidate, resolvedAppRoot))) {
      return resolvedCandidate;
    }
  }

  return defaultDirectoryRoot ? path.resolve(defaultDirectoryRoot) : path.resolve(cwd);
}
