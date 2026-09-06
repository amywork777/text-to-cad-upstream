import { beforeEach, expect, it, vi } from "vitest";
import { addCadSelection, useCadSelection } from "@renderer/state/cad-selection";
import { useComposer, newDraftKey } from "@renderer/state/composer";
import { useProjects } from "@renderer/state/projects";
import { useSessions } from "@renderer/state/sessions";
import { useExplorer } from "@renderer/state/explorer";
import { performCadCommand } from "@renderer/state/cad-commands";
import type { Session } from "@shared/types";

const selection = { projectId: "p", workspacePath: "/worktree", file: "part.step", refs: ["part:f1", "part:e2"] };
beforeEach(() => {
  vi.useFakeTimers();
  useProjects.setState({ projects: [{ id: "p", name: "Project", path: "/project", createdAt: 0 }], activeId: "p" });
  useSessions.setState({ activeId: null, sessions: [] });
  useComposer.setState({ drafts: {}, draftWorkspaces: {} });
  useExplorer.setState({ projectId: "p", tabs: [], activeId: null, ready: true });
});
it("appends to the project draft, preserves prose, deduplicates and pins its workspace", () => {
  const key = newDraftKey("p");
  useComposer.getState().setDraft(key, "Please chamfer these");
  addCadSelection(selection);
  addCadSelection(selection);
  expect(useComposer.getState().drafts[key]).toBe("Please chamfer these\npart:f1\npart:e2\n");
  expect(useComposer.getState().draftWorkspaces[key]).toBe("/worktree");
  expect(useComposer.getState().drafts[newDraftKey("other")]).toBeUndefined();
  expect(() => addCadSelection({ ...selection, workspacePath: "/other" })).toThrow(/another workspace/);
});
it("refuses an existing chat in another workspace without changing its draft", () => {
  useSessions.setState({ activeId: "s", sessions: [{ id: "s", projectId: "p", cwd: "/project" } as Session] });
  useComposer.getState().setDraft("s", "Keep this");
  expect(() => addCadSelection(selection)).toThrow(/workspace/);
  expect(useComposer.getState().drafts.s).toBe("Keep this");
  useSessions.setState({ sessions: [{ id: "s", projectId: "p", cwd: "/worktree" } as Session] });
  addCadSelection(selection);
  expect(useComposer.getState().drafts.s).toContain("Keep this\npart:f1");
});
it("keeps same-named files in different workspaces distinct and scopes viewer state", async () => {
  const first = useExplorer.getState().openFile("part.step");
  const second = useExplorer.getState().openFile("part.step", "/worktree");
  expect(first?.id).not.toBe(second?.id);
  expect(useExplorer.getState().openFile("part.step", "/worktree")?.id).toBe(second?.id);
  useCadSelection.setState({ selection });
  const command = { requestId: "r", projectId: "p", workspacePath: "/worktree", kind: "viewer-state" as const };
  expect(await performCadCommand(command)).toMatchObject({ file: "part.step", selection: selection.refs });
  expect(await performCadCommand({ ...command, workspacePath: "/project" })).toMatchObject({ file: null, selection: null });
  expect(await performCadCommand({ ...command, projectId: "other" })).toMatchObject({ file: null, selection: null });
});
