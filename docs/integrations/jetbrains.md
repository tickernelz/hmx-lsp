# JetBrains: PyCharm and IntelliJ IDEA

Plugin source: `editors/jetbrains`. It uses the official
`com.intellij.platform.lsp.serverSupportProvider` extension point, so PyCharm Professional or
IntelliJ IDEA Ultimate 2024.2+ is required (the LSP API is not available in Community editions).

## Install

Download `hmx-lsp-jetbrains-<version>.zip` from the release page, then
**Settings -> Plugins -> gear icon -> Install Plugin from Disk...** and restart.

To build it yourself:

```bash
cd editors/jetbrains
gradle buildPlugin
```

The artifact lands in `build/distributions/`.

## Pointing it at the binary

The plugin resolves `hmx-lsp` through the shared chain in `installation.md`. The two supported
overrides are:

**VM option** — *Help -> Edit Custom VM Options*, then restart:

```
-Dhmx.lsp.path=/home/you/.local/bin/hmx-lsp
```

**Environment variable** — must be exported before the IDE starts:

```bash
export HMX_LSP_PATH=/home/you/.local/bin/hmx-lsp
```

Generate both lines for your machine with:

```bash
hmx-lsp setup jetbrains
```

With neither set, the plugin still finds a binary in `<project>/.hmx/`, `<project>/bin/`,
`<project>/tools/`, `~/.hmx-lsp/bin/`, `~/.local/bin/`, `~/.cache/hmx-lsp/bin/`, or on `PATH`.
As a last resort it runs `python -m hmx_ls.cli serve` from a source checkout, using
`-Dhmx.lsp.pythonPath` or `python3`/`python` from `PATH`.

When nothing resolves, the plugin raises an error naming the exact asset it expected.
