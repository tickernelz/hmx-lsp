# VS Code & Cursor Integration

The HMX Language Server extension lives in `editors/vscode`.

## Installation

```bash
cd editors/vscode
npm install
npm run build
```

To install into VS Code or Cursor locally:
```bash
npx @vscode/vsce package
code --install-extension hmx-lsp-vscode-0.1.0.vsix
# Or in Cursor:
cursor --install-extension hmx-lsp-vscode-0.1.0.vsix
```

## Configuration (`.vscode/settings.json`)

```json
{
  "hmx.pythonPath": "/opt/conda/envs/hmx/bin/python",
  "hmx.serverModule": "hmx_ls.server",
  "hmx.trace.server": "off"
}
```
