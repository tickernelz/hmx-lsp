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
        return GeneralCommandLine().apply {
            exePath = "/opt/conda/envs/hmx/bin/python"
            addParameters("-m", "hmx_ls.server")
            setWorkDirectory(project.basePath)
        }
    }
}
