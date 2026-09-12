import * as path from "path";
import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;
let statusBarItem: vscode.StatusBarItem | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration("hmx");
  const pythonPath = config.get<string>("pythonPath", "/opt/conda/envs/hmx/bin/python");
  const serverModule = config.get<string>("serverModule", "hmx_ls.server");

  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.text = "$(gear~spin) HMX-LS: Starting";
  statusBarItem.command = "hmx.restartServer";
  statusBarItem.tooltip = "Click to restart HMX Language Server";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  const serverOptions: ServerOptions = {
    command: pythonPath,
    args: ["-m", serverModule],
    options: {
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
      },
    },
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: "file", language: "xml" },
      { scheme: "file", language: "python" },
      { scheme: "file", language: "javascript" },
      { scheme: "file", language: "vue" },
      { scheme: "file", pattern: "**/security/*.csv" },
    ],
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

  client = new LanguageClient(
    "hmxLanguageServer",
    "HMX Language Server",
    serverOptions,
    clientOptions
  );

  client.start().then(
    () => {
      if (statusBarItem) {
        statusBarItem.text = "$(check) HMX-LS";
      }
    },
    (error) => {
      if (statusBarItem) {
        statusBarItem.text = "$(error) HMX-LS: Failed";
      }
      vscode.window.showErrorMessage(`Failed to start HMX Language Server: ${error}`);
    }
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("hmx.restartServer", async () => {
      if (client) {
        if (statusBarItem) {
          statusBarItem.text = "$(gear~spin) HMX-LS: Restarting";
        }
        await client.stop();
        await client.start();
        if (statusBarItem) {
          statusBarItem.text = "$(check) HMX-LS";
        }
        vscode.window.showInformationMessage("HMX Language Server restarted.");
      }
    })
  );
}

export function deactivate(): Thenable<void> | undefined {
  if (statusBarItem) {
    statusBarItem.dispose();
  }
  if (!client) {
    return undefined;
  }
  return client.stop();
}
