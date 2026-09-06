import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, expect, test } from "@playwright/test";
import type { HardcoreApi } from "../../src/shared/ipc";
declare const window: { hardcore: HardcoreApi };
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("a car opens from the tree and its selection appends to the draft", async () => {
  test.skip(!process.env.HARDCORE_E2E_CAD_STEP, "set HARDCORE_E2E_CAD_STEP to an existing STEP fixture");
  test.setTimeout(150_000);
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "hardcore-cad-selection-"));
  const project = path.join(base, "project");
  fs.mkdirSync(project);
  fs.copyFileSync(process.env.HARDCORE_E2E_CAD_STEP!, path.join(project, "car.step"));
  const app = await electron.launch({ args: [path.join(appRoot, "out/main/index.js"), `--user-data-dir=${path.join(base, "profile")}`], env: { ...process.env, NODE_ENV: "test" } });
  const errors: string[] = [];
  try {
    const page = await app.firstWindow();
    page.on("pageerror", (error) => { errors.push(error.message); console.error("renderer error", error.message); });
    await page.waitForLoadState("domcontentloaded");
    await page.evaluate((root) => window.hardcore.projects.addPath({ path: root }), project);
    await page.getByRole("button", { name: "Toggle explorer", exact: true }).click();
    await page.getByRole("button", { name: "Open a file", exact: true }).click();
    await page.getByLabel("Filter files").fill("car.step");
    await page.getByRole("option", { name: "car.step", exact: false }).first().click();
    await expect(page.getByRole("tab", { name: /car\.step/ })).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 90_000 });
    const draft = page.getByPlaceholder("Do anything");
    await draft.fill("Please round this edge");
    const component = page.getByRole("treeitem", { name: /Component/ }).first();
    await expect(component).toBeVisible({ timeout: 60_000 });
    await component.click();
    await page.getByRole("button", { name: "Add selection to prompt" }).click();
    await expect(draft).toHaveValue(/Please round this edge\n.+/);
    await page.screenshot({ path: path.join(appRoot, "test-results/car-selection.png") });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    fs.rmSync(base, { recursive: true, force: true });
  }
});
