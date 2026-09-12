import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";
import { binaryName, downloadServer, resolveServer, storedBinary } from "./resolver";

let client: LanguageClient | undefined;
let statusBarItem: vscode.StatusBarItem | undefined;
let log: vscode.OutputChannel | undefined;

function documentSelector(): LanguageClientOptions["documentSelector"] {
  return [
    { scheme: "file", language: "xml" },
    { scheme: "file", language: "python" },
    { scheme: "file", language: "javascript" },
    { scheme: "file", language: "vue" },
    { scheme: "file", pattern: "**/security/*.csv" },
  ];
}

async function startClient(context: vscode.ExtensionContext): Promise<void> {
  const channel = log as vscode.OutputChannel;
  const resolved = await resolveServer(context, channel);

  if (!resolved) {
    if (statusBarItem) {
      statusBarItem.text = "$(error) HMX-LS: not found";
      statusBarItem.tooltip = "HMX language server binary could not be located. Click to retry.";
    }
    const choice = await vscode.window.showErrorMessage(
      `HMX language server not found. Expected ${binaryName()} on PATH, in HMX_LSP_PATH, or via hmx.server.path.`,
      "Download now",
      "Open settings",
      "Show log"
    );
    if (choice === "Download now") {
      const version = vscode.workspace.getConfiguration("hmx").get<string>("server.version", "latest");
      const downloaded = await downloadServer(context, version, channel);
      if (downloaded) {
        await startClient(context);
      }
    } else if (choice === "Open settings") {
      await vscode.commands.executeCommand("workbench.action.openSettings", "hmx.server.path");
    } else if (choice === "Show log") {
      channel.show();
    }
    return;
  }

  channel.appendLine(`[hmx-ls] using ${resolved.command} ${resolved.args.join(" ")} (${resolved.origin})`);

  const serverOptions: ServerOptions = {
    command: resolved.command,
    args: resolved.args,
    options: {
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: documentSelector(),
    outputChannel: channel,
    synchronize: {
      fileEvents: [
        vscode.workspace.createFileSystemWatcher("**/*.py"),
        vscode.workspace.createFileSystemWatcher("**/*.xml"),
        vscode.workspace.createFileSystemWatcher("**/*.js"),
        vscode.workspace.createFileSystemWatcher("**/*.vue"),
        vscode.workspace.createFileSystemWatcher("**/security/*.csv"),
      ],
    },
  };

  client = new LanguageClient("hmxLanguageServer", "HMX Language Server", serverOptions, clientOptions);

  try {
    await client.start();
    if (statusBarItem) {
      statusBarItem.text = "$(check) HMX-LS";
      statusBarItem.tooltip = `HMX Language Server running from ${resolved.origin}`;
    }
  } catch (error) {
    if (statusBarItem) {
      statusBarItem.text = "$(error) HMX-LS: failed";
    }
    channel.appendLine(`[hmx-ls] start failed: ${error}`);
    vscode.window.showErrorMessage(`Failed to start HMX Language Server: ${error}`);
  }
}

async function stopClient(): Promise<void> {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  log = vscode.window.createOutputChannel("HMX Language Server");
  context.subscriptions.push(log);

  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.text = "$(gear~spin) HMX-LS: starting";
  statusBarItem.command = "hmx.restartServer";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("hmx.restartServer", async () => {
      if (statusBarItem) {
        statusBarItem.text = "$(gear~spin) HMX-LS: restarting";
      }
      await stopClient();
      await startClient(context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("hmx.updateServer", async () => {
      const channel = log as vscode.OutputChannel;
      const version = vscode.workspace.getConfiguration("hmx").get<string>("server.version", "latest");
      await stopClient();
      const downloaded = await downloadServer(context, version, channel);
      if (downloaded) {
        vscode.window.showInformationMessage(`HMX Language Server updated: ${downloaded}`);
      }
      await startClient(context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("hmx.showServerPath", async () => {
      const channel = log as vscode.OutputChannel;
      const resolved = await resolveServer(context, channel);
      const message = resolved
        ? `${resolved.command} (${resolved.origin})`
        : `not found; expected ${binaryName()} — storage candidate ${storedBinary(context)}`;
      vscode.window.showInformationMessage(`HMX-LS: ${message}`);
      channel.appendLine(`[hmx-ls] resolved: ${message}`);
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      if (event.affectsConfiguration("hmx.server") || event.affectsConfiguration("hmx.pythonPath")) {
        await stopClient();
        await startClient(context);
      }
    })
  );

  await startClient(context);
}

export function deactivate(): Thenable<void> | undefined {
  statusBarItem?.dispose();
  if (!client) {
    return undefined;
  }
  return client.stop();
}
