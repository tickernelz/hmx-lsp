# HMX Language Server

Cross-layer language intelligence for HMX: Python ORM models, XML `baseuiview` views, Webx JS/Vue, security CSV, and `__hmx__.py` asset bundles.

It answers what no single-language server can: which model a view is bound to, whether a `<field name=...>` exists on it, where a widget is registered, whether a security CSV row names a real model, and whether an asset glob matches any file.

## The one thing to know before installing

**This extension is a client. The language server is a separate program.** Installing the `.vsix` alone is not enough — the extension has to find a server to talk to, or it will report:

> Client is not running and can't be stopped. It's current state is: startFailed

Pick exactly one of the three options below.

## Option 1 — let the extension download the server (default, nothing to install)

Leave the settings alone. On first activation the extension downloads the release binary for your platform into its own storage and starts it.

Requires network access to `github.com`. If your machine cannot reach it, use option 2 or 3.

## Option 2 — install the server yourself

Download the binary for your platform from the [releases page](https://github.com/tickernelz/hmx-lsp/releases), make it executable, and put it on your `PATH`:

```bash
curl -L -o hmx-lsp https://github.com/tickernelz/hmx-lsp/releases/latest/download/hmx-lsp-linux-x64
chmod +x hmx-lsp
sudo mv hmx-lsp /usr/local/bin/
hmx-lsp --version
```

Assets: `hmx-lsp-linux-x64`, `hmx-lsp-linux-arm64`, `hmx-lsp-darwin-x64`, `hmx-lsp-darwin-arm64`, `hmx-lsp-windows-x64.exe`.

If you would rather not touch `PATH`, point the setting at it instead:

```json
{ "hmx.server.path": "/absolute/path/to/hmx-lsp" }
```

## Option 3 — run from a source checkout

Useful when you are working on the server itself.

```bash
git clone https://github.com/tickernelz/hmx-lsp.git
cd hmx-lsp
pip install -r requirements.txt
```

The extension finds a checkout automatically when it sits at your workspace root, or one level inside it, and launches it through `bin/hmx-ls` so the interpreter does not need the package installed.

To be explicit instead, point the setting at the wrapper:

```json
{ "hmx.server.path": "/absolute/path/to/hmx-lsp/bin/hmx-ls" }
```

`pip install -e .` also works and puts `hmx-lsp` on your `PATH`, which turns this into option 2.

## WSL and remote workspaces

The extension runs where your code runs. On WSL the title says `Extension is enabled on 'WSL: ...'`, which means:

- the server must be the **Linux** binary, not the Windows `.exe`
- a server installed on the Windows side is invisible to it
- `hmx.server.path` must be a Linux path such as `/home/you/.local/bin/hmx-lsp`

The same applies to Dev Containers and Remote-SSH.

## How the server is located

In order, stopping at the first candidate that answers `--version` successfully:

1. `hmx.server.path`
2. `HMX_LSP_PATH`
3. a binary bundled with the extension
4. a binary previously downloaded by the extension
5. a source checkout at the workspace root or one level inside it
6. `hmx-lsp` or `hmx-ls` on `PATH`
7. a fresh download, if `hmx.server.autoDownload` is on

A candidate that exists but cannot run is skipped, and the reason is written to the output channel, so a broken entry no longer blocks the ones behind it.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `hmx.server.path` | `""` | Absolute path to the server. Empty means auto-resolve. |
| `hmx.server.autoDownload` | `true` | Download the release binary when nothing else is found. |
| `hmx.server.version` | `"latest"` | Release tag to download. |
| `hmx.pythonPath` | `""` | Interpreter for the source-checkout path. |

## Commands

- **HMX: Restart Language Server**
- **HMX: Show Language Server Log**
- **HMX: Download Language Server**

## When it will not start

Open **HMX: Show Language Server Log** first; it names every candidate it tried and why each was rejected.

| Log line | Meaning | Fix |
|---|---|---|
| `probe rejected ... No module named 'hmx_ls'` | A checkout was found but its dependencies are missing | `pip install -r requirements.txt` in the checkout |
| `probe failed ... ENOENT` | The configured path does not exist | Correct `hmx.server.path` |
| `probe failed ... EACCES` | The binary is not executable | `chmod +x` it |
| `hmx.server.path is not executable` | Path set but not runnable | Check the path, and that it is a Linux binary under WSL |
| No candidates at all | Nothing installed | Run **HMX: Download Language Server** |

The status bar shows the current state: `HMX-LS: ready`, `restarting`, or `not found`. Click it to retry.

## Verifying the server independently of the editor

```bash
hmx-lsp --version
hmx-lsp doctor
hmx-lsp check --root /path/to/hmx --layer xml
```

`doctor` prints the interpreter, platform, expected asset name and resolved root, which is usually enough to explain a failed start.
