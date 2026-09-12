import * as cp from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export interface ServerCommand {
  command: string;
  args: string[];
  origin: string;
}

const RELEASE_OWNER = "tickernelz";
const RELEASE_REPO = "hmx-lsp";

export function binaryName(): string {
  const platform = process.platform;
  const arch = process.arch;

  if (platform === "win32") {
    return arch === "arm64" ? "hmx-lsp-windows-arm64.exe" : "hmx-lsp-windows-x64.exe";
  }
  if (platform === "darwin") {
    return arch === "arm64" ? "hmx-lsp-darwin-arm64" : "hmx-lsp-darwin-x64";
  }
  return arch === "arm64" ? "hmx-lsp-linux-arm64" : "hmx-lsp-linux-x64";
}

function isExecutableFile(candidate: string): boolean {
  try {
    const stat = fs.statSync(candidate);
    if (!stat.isFile()) {
      return false;
    }
    if (process.platform !== "win32") {
      fs.accessSync(candidate, fs.constants.X_OK);
    }
    return true;
  } catch {
    return false;
  }
}

function expandHome(target: string): string {
  if (target.startsWith("~")) {
    return path.join(os.homedir(), target.slice(1));
  }
  return target;
}

function searchPath(exe: string): string | undefined {
  const raw = process.env.PATH || "";
  const sep = process.platform === "win32" ? ";" : ":";
  const exts = process.platform === "win32" ? ["", ".exe", ".cmd", ".bat"] : [""];
  for (const dir of raw.split(sep)) {
    if (!dir) {
      continue;
    }
    for (const ext of exts) {
      const candidate = path.join(dir, exe + ext);
      if (isExecutableFile(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
}

function workspaceRoots(): string[] {
  return (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
}

function resolvePython(): string | undefined {
  const configured = vscode.workspace.getConfiguration("hmx").get<string>("pythonPath", "");
  if (configured) {
    const expanded = expandHome(configured);
    if (isExecutableFile(expanded)) {
      return expanded;
    }
  }
  const pythonExt = vscode.workspace
    .getConfiguration("python")
    .get<string>("defaultInterpreterPath", "");
  if (pythonExt && isExecutableFile(expandHome(pythonExt))) {
    return expandHome(pythonExt);
  }
  for (const exe of ["python3", "python"]) {
    const found = searchPath(exe);
    if (found) {
      return found;
    }
  }
  return undefined;
}

function devCheckout(): ServerCommand | undefined {
  const interpreter = resolvePython();
  if (!interpreter) {
    return undefined;
  }
  for (const root of workspaceRoots()) {
    const candidates = [root, path.join(root, "hmx_lsp"), path.join(root, "..", "hmx_lsp")];
    for (const candidate of candidates) {
      if (fs.existsSync(path.join(candidate, "hmx_ls", "cli.py"))) {
        return {
          command: interpreter,
          args: ["-m", "hmx_ls.cli", "serve"],
          origin: "dev checkout at " + candidate,
        };
      }
    }
  }
  return undefined;
}

export function storedBinary(context: vscode.ExtensionContext): string {
  return path.join(context.globalStorageUri.fsPath, "bin", binaryName());
}

export function bundledBinary(context: vscode.ExtensionContext): string {
  return path.join(context.extensionPath, "server", binaryName());
}

export async function downloadServer(
  context: vscode.ExtensionContext,
  version: string,
  log: vscode.OutputChannel
): Promise<string | undefined> {
  const target = storedBinary(context);
  await fs.promises.mkdir(path.dirname(target), { recursive: true });

  const tag = version && version !== "latest" ? version : "main";
  const url =
    "https://github.com/" +
    RELEASE_OWNER +
    "/" +
    RELEASE_REPO +
    "/releases/download/" +
    tag +
    "/" +
    binaryName();
  log.appendLine("[hmx-ls] downloading " + url);

  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "hmx-lsp-vscode" },
      redirect: "follow",
    });
    if (!response.ok) {
      log.appendLine("[hmx-ls] download failed: HTTP " + response.status);
      return undefined;
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    const tmp = target + ".download";
    await fs.promises.writeFile(tmp, buffer);
    await fs.promises.chmod(tmp, 0o755);
    await fs.promises.rename(tmp, target);
    log.appendLine("[hmx-ls] installed " + target + " (" + buffer.length + " bytes)");
    return target;
  } catch (error) {
    log.appendLine("[hmx-ls] download error: " + error);
    return undefined;
  }
}

export async function resolveServer(
  context: vscode.ExtensionContext,
  log: vscode.OutputChannel
): Promise<ServerCommand | undefined> {
  const config = vscode.workspace.getConfiguration("hmx");

  const explicit = config.get<string>("server.path", "");
  if (explicit) {
    const expanded = expandHome(explicit);
    if (isExecutableFile(expanded)) {
      return { command: expanded, args: ["serve"], origin: "hmx.server.path setting" };
    }
    log.appendLine("[hmx-ls] hmx.server.path is not executable: " + expanded);
  }

  const fromEnv = process.env.HMX_LSP_PATH;
  if (fromEnv && isExecutableFile(expandHome(fromEnv))) {
    return { command: expandHome(fromEnv), args: ["serve"], origin: "HMX_LSP_PATH" };
  }

  const bundled = bundledBinary(context);
  if (isExecutableFile(bundled)) {
    return { command: bundled, args: ["serve"], origin: "bundled with extension" };
  }

  const stored = storedBinary(context);
  if (isExecutableFile(stored)) {
    return { command: stored, args: ["serve"], origin: "downloaded release" };
  }

  const onPath = searchPath("hmx-lsp") || searchPath("hmx-ls");
  if (onPath) {
    return { command: onPath, args: ["serve"], origin: "PATH" };
  }

  const dev = devCheckout();
  if (dev) {
    return dev;
  }

  if (config.get<boolean>("server.autoDownload", true)) {
    const version = config.get<string>("server.version", "latest");
    const downloaded = await downloadServer(context, version, log);
    if (downloaded && isExecutableFile(downloaded)) {
      return { command: downloaded, args: ["serve"], origin: "downloaded release" };
    }
  }

  return undefined;
}

export function probe(command: ServerCommand, log: vscode.OutputChannel): boolean {
  try {
    const result = cp.spawnSync(command.command, ["--version"], { timeout: 10000 });
    if (result.error) {
      log.appendLine("[hmx-ls] probe failed: " + result.error.message);
      return false;
    }
    return true;
  } catch (error) {
    log.appendLine("[hmx-ls] probe threw: " + error);
    return false;
  }
}
