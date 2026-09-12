# VS Code and Cursor

Extension source: `editors/vscode`.

## Install

Download `hmx-lsp-vscode.vsix` from the release page:

```bash
code --install-extension hmx-lsp-vscode.vsix
cursor --install-extension hmx-lsp-vscode.vsix
```

Or build it:

```bash
cd editors/vscode
npm ci
npm run build
npx @vscode/vsce package
```

## Zero configuration

On first activation the extension resolves the server through the chain documented in
`installation.md`. If nothing is found locally and `hmx.server.autoDownload` is on (the default),
it downloads the correct binary for your OS and CPU into its own global storage. Nothing to
configure.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `hmx.server.path` | `""` | Absolute path to `hmx-lsp`. Empty means auto-resolve. |
| `hmx.server.autoDownload` | `true` | Fetch the platform binary from GitHub releases when none is found. |
| `hmx.server.version` | `"latest"` | Release tag to download. |
| `hmx.pythonPath` | `""` | Interpreter used **only** when running from a source checkout. Empty means use the Python extension's interpreter, then `python3`/`python`. |
| `hmx.trace.server` | `"off"` | Trace JSON-RPC traffic. |

Changing any `hmx.server.*` setting restarts the client automatically.

## Commands

| Command | Purpose |
|---|---|
| `HMX: Restart Language Server` | Stop and restart the client |
| `HMX: Download or Update Language Server` | Force-download the configured release |
| `HMX: Show Resolved Language Server Path` | Print which binary is in use and where it came from |

The status bar shows `$(check) HMX-LS` when running; hovering reveals the resolution origin.
All resolution decisions are logged to the **HMX Language Server** output channel.
