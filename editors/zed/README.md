# HMX Language Server for Zed

Cross-layer language intelligence for HMX inside Zed.

## Requirements

**The language server is a separate program.** The extension does not bundle it.

```bash
curl -L -o hmx-lsp https://github.com/tickernelz/hmx-lsp/releases/latest/download/hmx-lsp-linux-x64
chmod +x hmx-lsp
sudo mv hmx-lsp /usr/local/bin/
hmx-lsp --version
```

## Install the extension

From the [releases page](https://github.com/tickernelz/hmx-lsp/releases), download `hmx-lsp-zed-extension.tar.gz` and unpack it, then in Zed: **Extensions -> Install Dev Extension**, and select the unpacked directory.

## Configure

Add to `.zed/settings.json` in your project, or to your user settings:

```json
{
  "lsp": {
    "hmx-ls": {
      "binary": { "path": "hmx-lsp", "arguments": ["serve"] }
    }
  },
  "languages": {
    "XML": { "language_servers": ["hmx-ls"] },
    "Python": { "language_servers": ["pyright", "hmx-ls"] },
    "JavaScript": { "language_servers": ["vtsls", "hmx-ls"] },
    "Vue.js": { "language_servers": ["vue-language-server", "hmx-ls"] }
  }
}
```

The `languages` block matters. Zed will not attach a server to a language that does not list it, so omitting it leaves the extension installed and silent.

Generate the block with absolute paths already filled in for your machine:

```bash
hmx-lsp setup zed
```

`"path"` may be a bare `hmx-lsp` when it is on your `PATH`; otherwise use an absolute path. Zed does not expand `~`.

## Running from a source checkout

Point `"path"` at the wrapper, which sets `PYTHONPATH` itself and therefore works from any working directory:

```json
{
  "lsp": {
    "hmx-ls": {
      "binary": {
        "path": "/absolute/path/to/hmx-lsp/bin/hmx-ls",
        "arguments": ["serve"]
      }
    }
  }
}
```

Install the dependencies first: `pip install -r requirements.txt`.

## Checking it works

Open an HMX XML view and hover a `<field name=...>`. If nothing happens, open the Zed log with **zed: open log** from the command palette and look for `hmx-ls`.

Confirm the server independently before blaming the extension:

```bash
hmx-lsp --version
hmx-lsp doctor
```
