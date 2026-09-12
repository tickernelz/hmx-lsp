package com.hashmicro.hmx.lsp

import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspServerSupportProvider
import com.intellij.platform.lsp.api.LspServerSupportProvider.LspServerStarter

class HmxLspServerSupportProvider : LspServerSupportProvider {
    override fun fileOpened(
        project: Project,
        file: VirtualFile,
        serverStarter: LspServerStarter
    ) {
        val ext = file.extension?.lowercase()
        if (ext in SUPPORTED_EXTENSIONS) {
            serverStarter.ensureServerStarted(HmxLspServerDescriptor(project))
        }
    }

    companion object {
        val SUPPORTED_EXTENSIONS = setOf("py", "xml", "js", "vue", "csv")
    }
}
