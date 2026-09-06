import { create } from "zustand";
import { newDraftKey, useComposer } from "./composer";
import { useProjects } from "./projects";
import { useSessions } from "./sessions";

export type CadSelection = { projectId: string; workspacePath: string; file: string; refs: string[] };
export const useCadSelection = create<{ selection: CadSelection | null }>(() => ({ selection: null }));

/** Append on an explicit click; never submit, replace a draft or retarget an existing chat. */
export function addCadSelection(selection: CadSelection): void {
  const project = useProjects.getState().projects.find((item) => item.id === selection.projectId);
  if (!project || useProjects.getState().activeId !== project.id) throw new Error("Open this model's project first.");
  const { activeId, sessions } = useSessions.getState();
  const session = sessions.find((item) => item.id === activeId);
  if (activeId && !session) throw new Error("Wait for this chat to load before adding references.");
  if (session && (session.projectId !== project.id || session.cwd !== selection.workspacePath)) {
    throw new Error("Choose a chat in this model's workspace, or start a new chat, to add these references.");
  }
  const key = session?.id ?? newDraftKey(project.id);
  const composer = useComposer.getState();
  const existingWorkspace = composer.draftWorkspaces[key];
  if (!session && existingWorkspace && existingWorkspace !== selection.workspacePath) {
    throw new Error("This draft already references another workspace.");
  }
  const refs = [...new Set(selection.refs)].filter(Boolean);
  if (!refs.length) return;
  const draft = composer.drafts[key] ?? "";
  const existing = new Set(draft.split("\n"));
  const added = refs.filter((ref) => !existing.has(ref));
  if (added.length) composer.setDraft(key, draft + (draft && !draft.endsWith("\n") ? "\n" : "") + added.join("\n") + "\n");
  if (!session) composer.setDraftWorkspace(key, selection.workspacePath);
}
