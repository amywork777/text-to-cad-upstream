import fs from "node:fs/promises";
import { FsError } from "../explorer/fs";
import { listWorktrees } from "./git";

/** A file tab may serve the project itself or an existing worktree of its repository. */
export async function fileWorkspace(projectRoot: string, workspacePath?: string): Promise<string> {
  const root = await fs.realpath(projectRoot);
  if (!workspacePath) return root;
  const requested = await fs.realpath(workspacePath);
  if (requested === root) return root;
  const worktrees = await listWorktrees(root);
  for (const worktree of worktrees) {
    if (!worktree.bare && await fs.realpath(worktree.path).catch(() => null) === requested) {
      return requested;
    }
  }
  throw new FsError("that workspace does not belong to this project");
}
