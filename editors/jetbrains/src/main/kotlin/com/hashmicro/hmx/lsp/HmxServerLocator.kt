package com.hashmicro.hmx.lsp

import com.intellij.openapi.project.Project
import com.intellij.openapi.util.SystemInfo
import java.io.File

data class HmxServerCommand(val command: String, val args: List<String>, val origin: String)

object HmxServerLocator {
    private val PYTHON_CANDIDATES = listOf("python3", "python")

    fun binaryName(): String {
        val arch = System.getProperty("os.arch", "").lowercase()
        val isArm = arch.contains("aarch64") || arch.contains("arm64")
        return when {
            SystemInfo.isWindows && isArm -> "hmx-lsp-windows-arm64.exe"
            SystemInfo.isWindows -> "hmx-lsp-windows-x64.exe"
            SystemInfo.isMac && isArm -> "hmx-lsp-darwin-arm64"
            SystemInfo.isMac -> "hmx-lsp-darwin-x64"
            isArm -> "hmx-lsp-linux-arm64"
            else -> "hmx-lsp-linux-x64"
        }
    }

    fun resolve(project: Project): HmxServerCommand? {
        settingsPath()?.let { return HmxServerCommand(it, listOf("serve"), "hmx.lsp.path property") }
        envPath()?.let { return HmxServerCommand(it, listOf("serve"), "HMX_LSP_PATH") }
        projectLocal(project)?.let { return HmxServerCommand(it, listOf("serve"), "project .hmx directory") }
        userLocal()?.let { return HmxServerCommand(it, listOf("serve"), "user cache directory") }
        onPath()?.let { return HmxServerCommand(it, listOf("serve"), "PATH") }
        return devCheckout(project)
    }

    private fun executable(path: String?): String? {
        if (path.isNullOrBlank()) return null
        val expanded = if (path.startsWith("~")) {
            System.getProperty("user.home") + path.substring(1)
        } else {
            path
        }
        val file = File(expanded)
        return if (file.isFile && file.canExecute()) file.absolutePath else null
    }

    private fun settingsPath(): String? = executable(System.getProperty("hmx.lsp.path"))

    private fun envPath(): String? = executable(System.getenv("HMX_LSP_PATH"))

    private fun projectLocal(project: Project): String? {
        val base = project.basePath ?: return null
        val names = listOf(binaryName(), if (SystemInfo.isWindows) "hmx-lsp.exe" else "hmx-lsp")
        for (dir in listOf("$base/.hmx", "$base/bin", "$base/tools")) {
            for (name in names) {
                executable("$dir/$name")?.let { return it }
            }
        }
        return null
    }

    private fun userLocal(): String? {
        val home = System.getProperty("user.home") ?: return null
        val dirs = listOf(
            "$home/.hmx-lsp/bin",
            "$home/.local/bin",
            "$home/.cache/hmx-lsp/bin"
        )
        val names = listOf(binaryName(), if (SystemInfo.isWindows) "hmx-lsp.exe" else "hmx-lsp")
        for (dir in dirs) {
            for (name in names) {
                executable("$dir/$name")?.let { return it }
            }
        }
        return null
    }

    private fun onPath(): String? {
        val raw = System.getenv("PATH") ?: return null
        val separator = if (SystemInfo.isWindows) ";" else ":"
        val names = if (SystemInfo.isWindows) {
            listOf("hmx-lsp.exe", "hmx-lsp.cmd", "hmx-lsp.bat", "hmx-lsp")
        } else {
            listOf("hmx-lsp", "hmx-ls")
        }
        for (dir in raw.split(separator)) {
            if (dir.isBlank()) continue
            for (name in names) {
                executable("$dir/$name")?.let { return it }
            }
        }
        return null
    }

    private fun findPython(): String? {
        executable(System.getProperty("hmx.lsp.pythonPath"))?.let { return it }
        val raw = System.getenv("PATH") ?: return null
        val separator = if (SystemInfo.isWindows) ";" else ":"
        for (dir in raw.split(separator)) {
            if (dir.isBlank()) continue
            for (name in PYTHON_CANDIDATES) {
                val candidate = if (SystemInfo.isWindows) "$dir/$name.exe" else "$dir/$name"
                executable(candidate)?.let { return it }
            }
        }
        return null
    }

    private fun devCheckout(project: Project): HmxServerCommand? {
        val base = project.basePath ?: return null
        val interpreter = findPython() ?: return null
        for (candidate in listOf(base, "$base/hmx_lsp", File(base).parent + "/hmx_lsp")) {
            if (File("$candidate/hmx_ls/cli.py").isFile) {
                return HmxServerCommand(
                    interpreter,
                    listOf("-m", "hmx_ls.cli", "serve"),
                    "dev checkout at $candidate"
                )
            }
        }
        return null
    }
}
