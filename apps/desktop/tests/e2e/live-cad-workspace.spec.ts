import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, expect, test } from "@playwright/test";
import type { HardcoreApi } from "../../src/shared/ipc";
declare const window: { hardcore: HardcoreApi };

// Opt-in: real provider turns in a disposable worktree; no developer checkout is edited.
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = process.env.HARDCORE_E2E_CAD_SOURCE;
for (const agentId of ["codex", "claude-code"]) {
  test(`${agentId} edits CAD in a worktree, opens it and resumes`, async () => {
    test.skip(process.env.HARDCORE_E2E_LIVE_CAD !== "1" || !source, "set HARDCORE_E2E_LIVE_CAD=1 and HARDCORE_E2E_CAD_SOURCE to a small model script");
    test.setTimeout(300_000);
    const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hardcore-live-cad-")));
    const project = path.join(base, "project");
    const worktree = path.join(base, "worktree");
    const userData = path.join(base, "profile");
    fs.mkdirSync(project);
    const git = (...args: string[]) => execFileSync("git", args, { cwd: project, env: { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_SYSTEM: "/dev/null" } });
    git("init", "-q");
    fs.mkdirSync(path.join(project, "models"));
    fs.copyFileSync(source!, path.join(project, "models", "car.py"));
    fs.writeFileSync(path.join(project, "AGENTS.md"), "This is an isolated automated CAD test. Do only the requested test operations. Do not update global memory or inspect unrelated projects. Use the cadgen executable on PATH.\n");
    git("add", ".");
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture");
    git("worktree", "add", "--detach", worktree);
    // Both providers can discover the current app hand-off skill without changing global plugins.
    for (const directory of [".agents", ".claude"]) {
      const skills = path.join(worktree, directory, "skills", "hardcore-app");
      fs.mkdirSync(skills, { recursive: true });
      fs.copyFileSync(path.join(appRoot, "skills", "hardcore-app", "SKILL.md"), path.join(skills, "SKILL.md"));
    }
    let app = await electron.launch({ args: [path.join(appRoot, "out/main/index.js"), `--user-data-dir=${userData}`], env: { ...process.env, NODE_ENV: "test" } });
    try {
      let page = await app.firstWindow();
      page.on("pageerror", (error) => console.error("renderer error", error.message));
      await page.waitForLoadState("domcontentloaded");
      const added = await page.evaluate((root) => window.hardcore.projects.addPath({ path: root }), project);
      const session = await page.evaluate(({ projectId, cwd, agentId }) => window.hardcore.sessions.create({ projectId, cwd, agentId, gitMode: "worktree" }), { projectId: added.id, cwd: worktree, agentId });
      await page.evaluate((id) => window.hardcore.sessions.setApprovalMode({ id, mode: "approve-for-me" }), session.id);
      let state = await page.evaluate((id) => window.hardcore.sessions.state({ id }), session.id);
      const model = state?.configOptions.find((option) => /model/i.test(option.id) && option.type === "select");
      expect(model).toBeDefined();
      if (model?.type === "select") {
        const option = model.options.find((item) => /sonnet|gpt-5\.4/.test(item.value)) ?? model.options[0]!;
        await page.evaluate(({ id, configId, value }) => window.hardcore.sessions.setConfigOption({ id, configId, value }), { id: session.id, configId: model.id, value: option.value });
        const selected = await page.evaluate((id) => window.hardcore.sessions.state({ id }), session.id);
        expect(selected?.configOptions.find((item) => item.id === model.id)?.currentValue).toBe(option.value);
      }
      const prompt = "This is an isolated integration test. Read the local hardcore-app skill. In models/car.py change BODY_LENGTH from 160.0 to 170.0, leaving all other dimensions alone. Run cadgen --version and python models/car.py. If it succeeds, call the Hardcore open_file tool for models/car.step. Do not start a viewer or update global memory. Reply briefly.";
      await page.evaluate(({ id, text }) => window.hardcore.sessions.prompt({ id, content: [{ type: "text", text }] }), { id: session.id, text: prompt });
      state = await page.evaluate((id) => window.hardcore.sessions.state({ id }), session.id);
      const parts = state?.turns.flatMap((turn) => turn.parts) ?? [];
      const calls = parts.filter((part) => part.type === "tool_call");
      expect(calls.some((call) => /open_file/.test(call.title ?? "") && call.status === "completed"), JSON.stringify(parts.filter((p) => p.type === "text" || p.type === "tool_call")).slice(-6000)).toBe(true);
      expect(fs.readFileSync(path.join(worktree, "models/car.py"), "utf8")).toContain("BODY_LENGTH = 170.0");
      expect(fs.readFileSync(path.join(project, "models/car.py"), "utf8")).toContain("BODY_LENGTH = 160.0");
      expect(fs.statSync(path.join(worktree, "models/car.step")).size).toBeGreaterThan(1000);
      await expect(page.getByRole("tab", { name: /car\.step/ })).toBeVisible();
      await expect(page.locator("canvas").first()).toBeVisible({ timeout: 90_000 });
      await page.screenshot({ path: path.join(appRoot, `test-results/live-${agentId}-car.png`) });
      await page.evaluate((id) => window.hardcore.sessions.close({ id }), session.id);
      await app.close();
      app = await electron.launch({ args: [path.join(appRoot, "out/main/index.js"), `--user-data-dir=${userData}`], env: { ...process.env, NODE_ENV: "test" } });
      page = await app.firstWindow();
      await page.waitForLoadState("domcontentloaded");
      const replay = await page.evaluate((id) => window.hardcore.sessions.load({ id }), session.id);
      expect(replay.turns.some((turn) => turn.role === "user")).toBe(true);
      const tabs = await page.evaluate((projectId) => window.hardcore.explorer.loadTabs({ projectId }), added.id);
      expect(tabs.some((tab) => tab.kind === "file" && tab.path === "models/car.step" && tab.workspacePath === worktree)).toBe(true);
    } finally {
      await app.close();
      fs.rmSync(base, { recursive: true, force: true });
    }
  });
}
