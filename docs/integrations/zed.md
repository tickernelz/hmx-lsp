# Zed

Extension source: `editors/zed`. Built as a WebAssembly module against `zed_extension_api`.

## Install as a dev extension

```bash
cd editors/zed
cargo build --release --target wasm32-wasip1
```

Then in Zed: **zed: extensions -> Install Dev Extension** and select `editors/zed`.

## Zero configuration

The extension resolves the server in this order:

1. `lsp.hmx-ls.binary.path` from your Zed settings
2. `HMX_LSP_PATH` from the worktree shell environment
3. `hmx-lsp` or `hmx-ls` on `PATH`
4. The matching asset from the latest GitHub release, downloaded and cached per version

Older cached versions are pruned automatically after a successful download.

## Optional explicit settings

`.zed/settings.json`:

```json
{
  "lsp": {
    "hmx-ls": {
      "binary": {
        "path": "hmx-lsp",
        "arguments": ["serve"]
      }
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

Generate this for your machine with `hmx-lsp setup zed`.

HMX-LS is listed alongside the general-purpose servers on purpose: it only answers cross-layer
HMX questions and delegates ordinary Python/JS/Vue intelligence to them.
