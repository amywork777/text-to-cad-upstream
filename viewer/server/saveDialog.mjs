// Native OS Save-As dialog (subprocess). Returns exactly one of:
// {path: abs}, {cancelled: true}, {unsupported: true}.
//
// Honors VIEWER_SAVE_DIALOG_FORCE_PATH (value "__cancel__" -> cancelled, else the
// forced path) and VIEWER_DISABLE_NATIVE_SAVE_DIALOG=1 (-> unsupported), so a
// headless run never pops a dialog.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function runCapture(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.error) {
    return { spawnError: result.error };
  }
  return { code: result.status, stdout: result.stdout || "", stderr: result.stderr || "" };
}

function pickDarwin(prompt, suggestedName, defaultDir) {
  const script = [
    "on run argv",
    "set thePrompt to item 1 of argv",
    "set theName to item 2 of argv",
    "set theDir to item 3 of argv",
    'if theDir is not "" then',
    "set chosen to (choose file name with prompt thePrompt default name theName default location (POSIX file theDir))",
    "else",
    "set chosen to (choose file name with prompt thePrompt default name theName)",
    "end if",
    "return POSIX path of chosen",
    "end run",
  ];
  const args = [];
  for (const line of script) {
    args.push("-e", line);
  }
  args.push(prompt, suggestedName, defaultDir || "");
  const res = runCapture("osascript", args);
  if (res.spawnError) {
    return { unsupported: true };
  }
  if (res.code === 0) {
    const chosen = res.stdout.trim();
    return chosen ? { path: chosen } : { cancelled: true };
  }
  return { cancelled: true, message: res.stderr.trim() };
}

function pickLinux(suggestedName, defaultDir) {
  const startPath = defaultDir ? path.join(defaultDir, suggestedName) : suggestedName;
  const zenity = runCapture("zenity", ["--file-selection", "--save", "--confirm-overwrite", `--filename=${startPath}`]);
  if (!zenity.spawnError) {
    if (zenity.code === 0) {
      const chosen = zenity.stdout.trim();
      return chosen ? { path: chosen } : { cancelled: true };
    }
    return { cancelled: true };
  }
  const kdialog = runCapture("kdialog", ["--getsavefilename", startPath]);
  if (!kdialog.spawnError) {
    if (kdialog.code === 0) {
      const chosen = kdialog.stdout.trim();
      return chosen ? { path: chosen } : { cancelled: true };
    }
    return { cancelled: true };
  }
  return { unsupported: true };
}

function pickWindows(suggestedName, defaultDir) {
  const quote = (value) => String(value).replace(/'/g, "''");
  const parts = [
    "Add-Type -AssemblyName System.Windows.Forms;",
    "$dialog = New-Object System.Windows.Forms.SaveFileDialog;",
    defaultDir ? `$dialog.InitialDirectory = '${quote(defaultDir)}';` : "",
    `$dialog.FileName = '${quote(suggestedName)}';`,
    "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dialog.FileName) }",
  ];
  const res = runCapture("powershell", ["-NoProfile", "-STA", "-Command", parts.filter(Boolean).join(" ")]);
  if (res.spawnError) {
    return { unsupported: true };
  }
  if (res.code === 0) {
    const chosen = res.stdout.trim();
    return chosen ? { path: chosen } : { cancelled: true };
  }
  return { cancelled: true };
}

export function pickSaveDestination({ suggestedName = "export", defaultDir = "", prompt = "Export model as:" } = {}) {
  const forced = String(process.env.VIEWER_SAVE_DIALOG_FORCE_PATH || "").trim();
  if (forced) {
    return forced === "__cancel__" ? { cancelled: true } : { path: forced };
  }
  if (process.env.VIEWER_DISABLE_NATIVE_SAVE_DIALOG === "1") {
    return { unsupported: true };
  }
  const safeDir = defaultDir && fs.existsSync(defaultDir) ? defaultDir : "";
  try {
    if (process.platform === "darwin") {
      return pickDarwin(prompt, suggestedName, safeDir);
    }
    if (process.platform === "win32") {
      return pickWindows(suggestedName, safeDir);
    }
    return pickLinux(suggestedName, safeDir);
  } catch {
    return { unsupported: true };
  }
}
