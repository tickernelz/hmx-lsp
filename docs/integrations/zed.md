# Zed Editor Integration

The HMX Language Server extension lives in `editors/zed`.

## Native Settings (`.zed/settings.json`)

```json
{
  "lsp": {
    "hmx-ls": {
      "binary": {
        "path": "/opt/conda/envs/hmx/bin/python",
        "arguments": ["-m", "hmx_ls.server"]
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
