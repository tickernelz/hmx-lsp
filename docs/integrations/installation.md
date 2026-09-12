# Installing HMX-LS

HMX-LS is a single self-contained executable. It bundles its own Python runtime and every
dependency, so nothing needs to be installed on the developer machine — no Python, no conda,
no pip.

## Download

Grab the asset for your platform from the release page:

| Platform | Asset |
|---|---|
| Linux x86_64 | `hmx-lsp-linux-x64` |
| Linux ARM64 | `hmx-lsp-linux-arm64` |
| Windows x86_64 | `hmx-lsp-windows-x64.exe` |
| macOS Apple Silicon | `hmx-lsp-darwin-arm64` |
| macOS Intel | `hmx-lsp-darwin-x64` |

```bash
curl -fsSL -o hmx-lsp \
  https://github.com/tickernelz/hmx-lsp/releases/latest/download/hmx-lsp-linux-x64
chmod +x hmx-lsp
mkdir -p ~/.local/bin && mv hmx-lsp ~/.local/bin/
hmx-lsp doctor
```

Every editor plugin can also download the binary for you, so this step is optional.

## How every plugin finds the binary

No plugin hardcodes an interpreter or an install path. They all walk the same chain and stop at
the first hit:

| Order | Source | Configure with |
|---:|---|---|
| 1 | Explicit editor setting | `hmx.server.path` (VS Code), `hmx.lsp.path` VM option (JetBrains), `lsp.hmx-ls.binary.path` (Zed) |
| 2 | Environment variable | `HMX_LSP_PATH=/abs/path/to/hmx-lsp` |
| 3 | Binary bundled inside the plugin | shipped in the `.vsix` under `server/` |
| 4 | Previously downloaded release | plugin-managed cache directory |
| 5 | Project-local directory | `<project>/.hmx/`, `<project>/bin/`, `<project>/tools/` |
| 6 | User directory | `~/.hmx-lsp/bin/`, `~/.local/bin/`, `~/.cache/hmx-lsp/bin/` |
| 7 | `PATH` | `hmx-lsp`, or `hmx-ls` |
| 8 | Source checkout | falls back to `python -m hmx_ls.cli serve` when `hmx_ls/cli.py` is present |
| 9 | GitHub release download | VS Code and Zed fetch the correct asset automatically |

For a whole team the simplest setup is step 7: drop the binary on `PATH` once. For a repo-pinned
version, commit nothing and instead use step 5 with `.hmx/` gitignored.

## Verify

```bash
hmx-lsp --version
hmx-lsp doctor
```

`doctor` prints the resolved interpreter, platform, expected asset name, launch command,
`HMX_LSP_PATH`, `HMX_ROOT`, the detected HMX repository root, and whether the binary is on `PATH`.
It exits non-zero when a runtime dependency is missing.

## Repository root detection

Commands that need the HMX corpus resolve the root in this order: an explicit `--root`, the
`HMX_ROOT` environment variable, then by walking up from the working directory looking for
`hmx/module/`. The LSP server uses the editor's workspace root.
