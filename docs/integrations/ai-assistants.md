# AI Assistants: Claude Code, Codex, OMP

HMX-LS ships a Model Context Protocol server. Point the assistant at the `hmx-lsp` binary — no Python required.

Generate the exact snippet for your machine:

```bash
hmx-lsp setup claude
hmx-lsp setup codex
hmx-lsp setup omp
```

## Claude Code

```bash
claude mcp add hmx-lsp hmx-lsp mcp
```

Or `.mcp.json`:

```json
{
  "mcpServers": {
    "hmx-lsp": {
      "command": "hmx-lsp",
      "args": ["mcp"],
      "env": { "HMX_ROOT": "/path/to/hmx-002" }
    }
  }
}
```

## Codex

```json
{
  "mcp_servers": {
    "hmx-lsp": {
      "command": "hmx-lsp",
      "args": ["mcp"],
      "env": { "HMX_ROOT": "/path/to/hmx-002" }
    }
  }
}
```

## Oh My Pi (OMP)

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

`HMX_ROOT` is optional — when omitted the server walks up from the working directory looking for `hmx/module/`.

## Tools exposed

| Tool | Purpose |
|---|---|
| `hmx_definition(file_path, line, col)` | Resolve a cross-layer reference to its declaration |
| `hmx_hover(file_path, line, col)` | Markdown metadata for a field, model, widget, or decorator |
| `hmx_model_info(model_name)` | Composed fields, methods, and inheritance chain |
| `hmx_where_used(model_name, field_name)` | Usages across Python, XML, Webx, and security CSV |
| `hmx_diagnose(file_path)` | Multi-layer validation for one file |
