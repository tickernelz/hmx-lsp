# HMX Language Server for JetBrains

Cross-layer language intelligence for HMX inside PyCharm and other IntelliJ-platform IDEs.

## Requirements you cannot skip

**PyCharm Professional, or another paid JetBrains IDE.** The plugin is built against the IntelliJ Platform LSP API, which ships only in the commercial IDEs. It will not load in PyCharm Community or IntelliJ IDEA Community.

Minimum build: `242` (2024.2).

**The language server is a separate program.** The plugin does not bundle it.

## Install

1. Install the server and confirm it runs:

   ```bash
   curl -L -o hmx-lsp https://github.com/tickernelz/hmx-lsp/releases/latest/download/hmx-lsp-linux-x64
   chmod +x hmx-lsp
   sudo mv hmx-lsp /usr/local/bin/
   hmx-lsp --version
   ```

2. Install the plugin: **Settings -> Plugins -> gear icon -> Install Plugin from Disk**, pick `hmx-lsp-jetbrains-<version>.zip` from the [releases page](https://github.com/tickernelz/hmx-lsp/releases).

3. Restart the IDE.

## Pointing the plugin at the server

If `hmx-lsp` is on your `PATH`, nothing further is needed.

Otherwise set the path explicitly. **Help -> Edit Custom VM Options**, add:

```
-Dhmx.lsp.path=/absolute/path/to/hmx-lsp
```

Then restart the IDE. A VM option only takes effect on restart.

The environment variable works too, but only if the IDE inherits it:

```bash
export HMX_LSP_PATH=/absolute/path/to/hmx-lsp
```

A desktop launcher usually does **not** inherit your shell profile. Launch the IDE from a terminal in that same shell, or use the VM option instead.

Generate both lines for your machine with:

```bash
hmx-lsp setup jetbrains
```

## Running from a source checkout

Point the VM option at the wrapper rather than a binary:

```
-Dhmx.lsp.path=/absolute/path/to/hmx-lsp/bin/hmx-ls
```

The wrapper sets `PYTHONPATH` itself, so it works regardless of the IDE's working directory. Install the dependencies first with `pip install -r requirements.txt`.

## Checking it works

**View -> Tool Windows -> Language Servers** lists `hmx-ls` and its state. If it is missing or red, check **Help -> Show Log in Files** for `hmx.lsp`.

Before blaming the plugin, confirm the server itself is healthy:

```bash
hmx-lsp --version
hmx-lsp doctor
```

## Building the plugin from source

Needs JDK 17 and Gradle 9.0 or newer; the build pins IntelliJ Platform Gradle Plugin 2.18.1, which refuses to apply on older Gradle.

```bash
cd editors/jetbrains
gradle buildPlugin
```

The artifact lands in `build/distributions/`.
