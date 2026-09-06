import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, expect, test } from "@playwright/test";
import type { HardcoreApi } from "../../src/shared/ipc";
declare const window: { hardcore: HardcoreApi };
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

for (const agentId of ["codex", "claude-code"]) {
  test(`${agentId} displays a real subagent, queues a prompt and replays the child`, async () => {
    test.skip(process.env.HARDCORE_E2E_LIVE_CAD !== "1", "set HARDCORE_E2E_LIVE_CAD=1 for real provider turns");
    test.setTimeout(240_000);
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "hardcore-live-child-"));
    const project = path.join(base, "project");
    fs.mkdirSync(project);
    fs.writeFileSync(path.join(project, "README.md"), "The verification marker is AMBER_CAR.\n");
    fs.writeFileSync(path.join(project, "AGENTS.md"), "This is an isolated integration test. Do only requested operations. Do not update memory or read unrelated files.\n");
    const app = await electron.launch({ args: [path.join(appRoot, "out/main/index.js"), `--user-data-dir=${path.join(base, "profile")}`], env: { ...process.env, NODE_ENV: "test" } });
    try {
      const page = await app.firstWindow();
      await page.waitForLoadState("domcontentloaded");
      const added = await page.evaluate((root) => window.hardcore.projects.addPath({ path: root }), project);
      const session = await page.evaluate(({ projectId, agentId }) => window.hardcore.sessions.create({ projectId, agentId, gitMode: "none" }), { projectId: added.id, agentId });
      await page.evaluate((id) => window.hardcore.sessions.setApprovalMode({ id, mode: "approve-for-me" }), session.id);
      await page.locator(`[data-session-row="${session.id}"]`).getByRole("button").first().click();
      const draft = page.getByPlaceholder("Do anything");
      await draft.fill("Delegate one read-only subagent to read README.md and report its verification marker. Wait for it to finish. Do not read the file yourself or change files. Reply with the marker it found. This is an automated subagent integration check.");
      await draft.press("Enter");
      await expect(page.locator("[data-session-view]")).toHaveAttribute("data-session-status", "running", { timeout: 60_000 });
      const queued = page.locator("textarea").first();
      await queued.fill("Reply with exactly QUEUED_OK. No tools are needed.");
      await queued.press("Enter");
      await expect(page.getByText("1 queued prompt")).toBeVisible();
      await expect(page.getByText("1 queued prompt")).toBeHidden({ timeout: 150_000 });
      await expect(page.locator("[data-session-view]")).toHaveAttribute("data-session-status", "idle", { timeout: 120_000 });
      const state = await page.evaluate((id) => window.hardcore.sessions.state({ id }), session.id);
      const parts = state?.turns.flatMap((turn) => turn.parts) ?? [];
      const child = parts.find((part) => part.type === "subagent" || (part.type === "tool_call" && part.children.length > 0));
      expect(child, JSON.stringify(parts).slice(-6000)).toBeDefined();
      expect(JSON.stringify(parts)).toContain("AMBER_CAR");
      expect(JSON.stringify(parts)).toContain("QUEUED_OK");
      await page.evaluate((id) => window.hardcore.sessions.close({ id }), session.id);
      const replay = await page.evaluate((id) => window.hardcore.sessions.load({ id }), session.id);
      // Claude ACP 0.75.1 replays parent messages but no child events for this
      // real session. Keep the assertion: an upstream fix becomes an unexpected
      // pass so we remove this documented limitation instead of silently skipping it.
      test.fail(agentId === "claude-code", "Claude ACP omits child events from session/load; live child and queue assertions above must still pass");
      expect(replay.turns.flatMap((turn) => turn.parts).some((part) => part.type === "subagent" || (part.type === "tool_call" && part.children.length > 0))).toBe(true);
    } finally {
      await app.close();
      fs.rmSync(base, { recursive: true, force: true });
    }
  });
}
