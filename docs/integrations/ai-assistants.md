# AI Assistants Integration: Claude Code, Codex, and OMP

HMX-LS ships with a native Model Context Protocol (MCP) server (`hmx_ls/mcp.py`) and unified CLI (`bin/hmx-ls`) to give AI coding agents cross-layer superpowers.

## 1. Claude Code

Add HMX-LS to your project's `.mcp.json` or global `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "hmx-lsp": {
      "command": "/opt/conda/envs/hmx/bin/python",
      "args": ["-m", "hmx_ls.cli", "mcp"],
      "env": {
        "HMX_ROOT": "/path/to/hmx-002"
      }
    }
  }
}
```

Or via CLI:
```bash
claude mcp add hmx-lsp /opt/conda/envs/hmx/bin/python -m hmx_ls.cli mcp
```

## 2. Codex (OpenAI)

In your Codex configuration or `mcp_servers.json`:

```json
{
  "mcp_servers": {
    "hmx": {
      "command": "/opt/conda/envs/hmx/bin/python",
      "args": ["-m", "hmx_ls.cli", "mcp"],
      "env": {
        "HMX_ROOT": "/path/to/hmx-002"
      }
    }
  }
}
```

## 3. Oh My Pi (OMP)

In `.omp/agent/config.yml` or `~/.omp/agent/config.yml`:

```yaml
mcp:
  servers:
    hmx:
      command: /opt/conda/envs/hmx/bin/python
      args:
        - -m
        - hmx_ls.cli
        - mcp
      env:
        HMX_ROOT: /home/zhafron/Works/HMX/hmx-002
```

## Available AI Tools

- `hmx_definition(file_path, line, col)`: Jump from XML/JS/CSV directly to Python definitions.
- `hmx_hover(file_path, line, col)`: Extract Markdown documentation for fields, models, and decorators.
- `hmx_model_info(model_name)`: Query composed fields, methods, and inheritance hierarchy.
- `hmx_where_used(model_name, field_name)`: Search all usages across Python, XML, Webx, and CSV.
- `hmx_diagnose(file_path)`: Run multi-layer diagnostics on any file and report issues.
