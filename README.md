# HMX Language Server (HMX-LS)

High-performance, cross-layer language server and Model Context Protocol (MCP) server for the HMX enterprise framework.

HMX-LS resolves references across four distinct language layers:
1. **Python ORM**: Models, fields, mixins, inheritance chains, and `@api.*` decorators (`@api.depends`, `@api.onchange`, `@api.constrains`, `@api.model`, `@api.transition`).
2. **XML Views & Architecture**: `<record model="baseuiview">`, nested subview comodel navigation, `<xpath>` target evaluation, and widget references.
3. **Webx Frontend**: Vue component mappings, `FieldRegistry`, `ListFieldRegistry`, and RPC `call_kw` handlers.
4. **Security & Routes**: CSV ACLs (`base.model.access.csv`), security groups, and Django Ninja API endpoints.

---

## Features

- **Cross-Layer Definition (`gd`)**: Jump from XML `<field name="...">` to Python model declaration, from `<xpath expr="...">` to the exact line in the inherited parent view, and from JS `call_kw` to Python methods.
- **Inheritance Resolution**: Automatically composes fields, methods, and comodel relations across `Meta.inherit`, `Meta.inherits`, Python base classes, and mixins.
- **Context-Aware Completion**: Autocompletes valid fields, models, widgets, XMLIDs, security groups, and HMX decorator snippets.
- **Live Diagnostics**: Validates XML views, Python relational fields, security CSVs, and JS RPC calls in real time.
- **Cross-Layer Refactor Rename**: Renames fields across Python declarations, `@api` decorators, and XML views in one atomic workspace edit.
- **Document Links**: Interactive hyperlinks on model names, XMLIDs, widgets, and API routes.
- **AI Coding Integration (MCP)**: Native Model Context Protocol server for Claude Code, Codex, and Oh My Pi (OMP).

---

## Architecture & Binary Distribution

HMX-LS is distributed as closed-source native standalone binaries compiled for:
- **Linux x86_64** (`hmx-lsp-linux-x64`)
- **Linux ARM64 / aarch64** (`hmx-lsp-linux-arm64`)
- **Windows x86_64** (`hmx-lsp-windows-x64.exe`)
- **macOS x86_64 Intel** (`hmx-lsp-darwin-x64`)
- **macOS ARM64 Apple Silicon** (`hmx-lsp-darwin-arm64`)

Binaries bundle all dependencies and the runtime environment into a single executable with zero external installation prerequisites.

---

## Editor Extensions

### 1. VS Code / Cursor
Extension lives in `editors/vscode`.
```bash
cd editors/vscode
npm install && npm run build
npx @vscode/vsce package
code --install-extension hmx-lsp-vscode-0.1.0.vsix
```

### 2. JetBrains PyCharm / IntelliJ
Plugin lives in `editors/jetbrains`.
```bash
cd editors/jetbrains
./gradlew buildPlugin
```
Install the generated `.zip` via **Settings -> Plugins -> Install Plugin from Disk...**.

### 3. Zed Editor
Extension lives in `editors/zed`. Add to `.zed/settings.json`:
```json
{
  "lsp": {
    "hmx-ls": {
      "binary": {
        "path": "hmx-lsp",
        "arguments": ["serve"]
      }
    }
  }
}
```

---

## AI Assistants (MCP)

### Claude Code
Add to `.mcp.json`:
```json
{
  "mcpServers": {
    "hmx-lsp": {
      "command": "hmx-lsp",
      "args": ["mcp"],
      "env": {
        "HMX_ROOT": "/path/to/hmx-002"
      }
    }
  }
}
```

### Oh My Pi (OMP)
Add to `.omp/agent/config.yml`:
```yaml
mcp:
  servers:
    hmx:
      command: hmx-lsp
      args:
        - mcp
      env:
        HMX_ROOT: /path/to/hmx-002
```

---

## CLI Usage

```bash
# Start LSP server via stdio
hmx-lsp serve

# Start MCP server for AI assistants
hmx-lsp mcp --root /path/to/hmx-002

# Inspect model inheritance, composed fields, and methods
hmx-lsp inspect hremployee --root /path/to/hmx-002

# Find all usages of a model or field across 4 layers
hmx-lsp where-used hremployee department_id --root /path/to/hmx-002

# Run repo-wide validation gate
hmx-lsp check --root /path/to/hmx-002
```
