import { spawn } from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import type { MarkItDownSettings } from "./settings";

export interface CliResult {
  code: number;
  stdout: string;
  stderr: string;
}

export interface ConversionRecord {
  source: string;
  output: string | null;
  ok: boolean;
  message: string;
}

export interface ProbeResult {
  ok: boolean;
  message: string;
  interpreter: string;
  python: string;
  markitdownVersion: string;
}

const IS_WINDOWS = process.platform === "win32";

/**
 * Candidate checkouts, most specific first.
 *
 * The plugin lives inside the vault, so it cannot assume any fixed relationship
 * to the converter; the configured path wins, then the conventional locations.
 */
function candidateRoots(settings: MarkItDownSettings): string[] {
  const roots: string[] = [];
  if (settings.projectRoot) roots.push(settings.projectRoot);
  const env = process.env.FOLDMARK_ROOT;
  if (env) roots.push(env);
  const home = os.homedir();
  roots.push(
    path.join(home, "foldmark"),
    path.join(home, "Documents", "foldmark"),
    path.join(home, "Claude", "Projects", "MicrosoftMarkItDown")
  );
  return roots;
}

export function resolveProjectRoot(settings: MarkItDownSettings): string | null {
  for (const root of candidateRoots(settings)) {
    try {
      if (fs.existsSync(path.join(root, "foldmark", "cli.py"))) return root;
    } catch {
      // An unreadable candidate is simply not the one.
    }
  }
  return null;
}

export function resolveInterpreter(settings: MarkItDownSettings, root: string | null): string[] {
  if (settings.pythonPath) return [settings.pythonPath];
  if (root) {
    const venv = IS_WINDOWS
      ? path.join(root, ".venv", "Scripts", "python.exe")
      : path.join(root, ".venv", "bin", "python");
    if (fs.existsSync(venv)) return [venv];
  }
  return IS_WINDOWS ? ["py", "-3"] : ["python3"];
}

function run(command: string[], cwd: string | undefined, timeoutMs: number): Promise<CliResult> {
  return new Promise((resolve) => {
    const [executable, ...rest] = command;
    const child = spawn(executable, rest, { cwd, windowsHide: true });
    let stdout = "";
    let stderr = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ code: 124, stdout, stderr: `Timed out after ${Math.round(timeoutMs / 1000)}s.` });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => (stdout += chunk.toString()));
    child.stderr.on("data", (chunk) => (stderr += chunk.toString()));
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: 127, stdout, stderr: error.message });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

async function runCli(
  settings: MarkItDownSettings,
  args: string[],
  timeoutMs: number
): Promise<{ result: CliResult; interpreter: string; root: string | null }> {
  const root = resolveProjectRoot(settings);
  const interpreter = resolveInterpreter(settings, root);
  if (!root) {
    return {
      result: {
        code: 127,
        stdout: "",
        stderr:
          "Could not find a checkout of Foldmark. Set the converter location in settings.",
      },
      interpreter: interpreter.join(" "),
      root,
    };
  }
  const command = [...interpreter, "-m", "foldmark.cli", ...args];
  const result = await run(command, root, timeoutMs);
  return { result, interpreter: interpreter.join(" "), root };
}

export async function probeConverter(settings: MarkItDownSettings): Promise<ProbeResult> {
  const { result, interpreter } = await runCli(settings, ["version", "--json"], 30000);
  if (result.code !== 0) {
    return {
      ok: false,
      message: (result.stderr || "The converter did not run.").trim().split("\n")[0],
      interpreter,
      python: "",
      markitdownVersion: "",
    };
  }
  try {
    const payload = JSON.parse(result.stdout);
    const markitdownVersion = String(payload.markitdown_version ?? "not detected");
    if (markitdownVersion === "not detected") {
      return {
        ok: false,
        message:
          "Python works, but Microsoft MarkItDown is not installed. Run the project's setup script.",
        interpreter,
        python: String(payload.python ?? ""),
        markitdownVersion,
      };
    }
    return {
      ok: true,
      message: "",
      interpreter: String(payload.executable ?? interpreter),
      python: String(payload.python ?? ""),
      markitdownVersion,
    };
  } catch {
    return {
      ok: false,
      message: "The converter returned output this plugin could not read.",
      interpreter,
      python: "",
      markitdownVersion: "",
    };
  }
}

/**
 * Convert into a scratch directory in one Python process.
 *
 * Batching matters: starting Python and importing MarkItDown costs a second or
 * more, so a folder of fifty files must not pay that fifty times. The caller
 * then imports the results through the vault API so Obsidian indexes them.
 */
export async function convertToTempDir(
  settings: MarkItDownSettings,
  sources: string[]
): Promise<{ records: ConversionRecord[]; skipped: string[]; tempDir: string; error?: string }> {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "markitdown-"));
  const { result } = await runCli(
    settings,
    ["convert", ...sources, "--out", tempDir, "--json"],
    Math.max(settings.timeoutSeconds, 10) * 1000
  );

  if (result.code === 2 || (result.code !== 0 && !result.stdout.trim())) {
    return {
      records: [],
      skipped: [],
      tempDir,
      error: (result.stderr || "Conversion failed.").trim().split("\n")[0],
    };
  }
  try {
    const payload = JSON.parse(result.stdout);
    return {
      records: (payload.results ?? []) as ConversionRecord[],
      skipped: (payload.skipped ?? []) as string[],
      tempDir,
    };
  } catch {
    return { records: [], skipped: [], tempDir, error: "The converter returned unreadable output." };
  }
}

export function cleanupTempDir(tempDir: string): void {
  try {
    fs.rmSync(tempDir, { recursive: true, force: true });
  } catch {
    // A leftover file in the OS temp folder is harmless.
  }
}
