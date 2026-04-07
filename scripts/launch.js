#!/usr/bin/env node
/**
 * Cross-platform Python launcher for Draco Dataset Studio.
 *
 * Resolves the correct Python executable (trying the Windows py launcher first,
 * then python3/python), then delegates to scripts/run_local_app.py.
 * All command-line arguments are forwarded transparently.
 */
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

const launchScript = path.join(__dirname, "run_local_app.py");
const forwardArgs = process.argv.slice(2);

// On Windows the official installer creates the 'py' launcher;
// 'python' may or may not be on PATH depending on install options.
const candidates =
  process.platform === "win32" ? ["py", "python"] : ["python3", "python"];

for (const py of candidates) {
  const result = spawnSync(py, [launchScript, ...forwardArgs], {
    stdio: "inherit",
    shell: false,
  });

  if (result.error && result.error.code === "ENOENT") {
    // This candidate was not found — try the next one.
    continue;
  }

  process.exit(result.status ?? 1);
}

process.stderr.write(
  "[draco] Python was not found on PATH.\n" +
    "  Windows : install Python 3.11+ from https://www.python.org/downloads/\n" +
    "            Make sure 'Add python.exe to PATH' is checked during install.\n" +
    "            Then reopen your terminal and retry.\n" +
    "  macOS   : brew install python@3.13  (or python@3.12, python@3.11)\n" +
    "  Linux   : sudo apt install python3  (or your distro equivalent)\n" +
    "\n" +
    "  Windows users: double-click run-portable.bat — it handles Python setup\n" +
    "  automatically without requiring PATH configuration.\n"
);
process.exit(1);
