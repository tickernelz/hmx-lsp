package com.hashmicro.hmx.lsp

import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.ProjectWideLspServerDescriptor

class HmxLspServerDescriptor(project: Project) : ProjectWideLspServerDescriptor(project, "HMX-LS") {
    override fun isSupportedFile(file: VirtualFile): Boolean {
        val ext = file.extension?.lowercase()
        return ext in HmxLspServerSupportProvider.SUPPORTED_EXTENSIONS
    }

    override fun createCommandLine(): GeneralCommandLine {
        val resolved = HmxServerLocator.resolve(project)
            ?: throw IllegalStateException(
                "HMX language server not found. Set HMX_LSP_PATH, put ${HmxServerLocator.binaryName()} on PATH, " +
                    "or place it at <project>/.hmx/${HmxServerLocator.binaryName()}."
            )

        return GeneralCommandLine().apply {
            exePath = resolved.command
            addParameters(resolved.args)
            withWorkDirectory(project.basePath)
            withEnvironment("PYTHONUNBUFFERED", "1")
        }
    }
}
