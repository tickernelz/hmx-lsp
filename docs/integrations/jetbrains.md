# JetBrains / PyCharm Integration

The HMX Language Server plugin lives in `editors/jetbrains`.

## Build

```bash
cd editors/jetbrains
./gradlew buildPlugin
```

The output zip will be placed in `build/distributions/hmx-lsp-jetbrains-0.1.0.zip`.
In PyCharm / IntelliJ IDEA:
1. Open **Settings** -> **Plugins**.
2. Click the gear icon -> **Install Plugin from Disk...**.
3. Select `hmx-lsp-jetbrains-0.1.0.zip`.
4. Restart IDE.
