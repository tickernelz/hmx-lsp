use std::fs;
use zed_extension_api::{
    self as zed, settings::LspSettings, Command, DownloadedFileType, LanguageServerId, Result,
};

const RELEASE_REPO: &str = "tickernelz/hmx-lsp";

struct HmxExtension {
    cached_path: Option<String>,
}

fn asset_name() -> Result<String> {
    let (platform, arch) = zed::current_platform();
    let name = match (platform, arch) {
        (zed::Os::Mac, zed::Architecture::Aarch64) => "hmx-lsp-darwin-arm64",
        (zed::Os::Mac, _) => "hmx-lsp-darwin-x64",
        (zed::Os::Linux, zed::Architecture::Aarch64) => "hmx-lsp-linux-arm64",
        (zed::Os::Linux, _) => "hmx-lsp-linux-x64",
        (zed::Os::Windows, zed::Architecture::Aarch64) => "hmx-lsp-windows-arm64.exe",
        (zed::Os::Windows, _) => "hmx-lsp-windows-x64.exe",
    };
    Ok(name.to_string())
}

impl HmxExtension {
    fn configured_binary(
        &self,
        language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Option<Command> {
        let settings = LspSettings::for_worktree(language_server_id.as_ref(), worktree).ok()?;
        let binary = settings.binary?;
        let path = binary.path?;
        Some(Command {
            command: path,
            args: binary.arguments.unwrap_or_else(|| vec!["serve".to_string()]),
            env: Default::default(),
        })
    }

    fn from_environment(&self, worktree: &zed::Worktree) -> Option<Command> {
        for (key, value) in worktree.shell_env() {
            if key == "HMX_LSP_PATH" && !value.is_empty() {
                return Some(Command {
                    command: value,
                    args: vec!["serve".to_string()],
                    env: Default::default(),
                });
            }
        }
        None
    }

    fn from_path(&self, worktree: &zed::Worktree) -> Option<Command> {
        for name in ["hmx-lsp", "hmx-ls"] {
            if let Some(found) = worktree.which(name) {
                return Some(Command {
                    command: found,
                    args: vec!["serve".to_string()],
                    env: Default::default(),
                });
            }
        }
        None
    }

    fn download(&mut self, language_server_id: &LanguageServerId) -> Result<String> {
        if let Some(cached) = &self.cached_path {
            if fs::metadata(cached).map_or(false, |stat| stat.is_file()) {
                return Ok(cached.clone());
            }
        }

        zed::set_language_server_installation_status(
            language_server_id,
            &zed::LanguageServerInstallationStatus::CheckingForUpdate,
        );

        let release = zed::latest_github_release(
            RELEASE_REPO,
            zed::GithubReleaseOptions {
                require_assets: true,
                pre_release: false,
            },
        )?;

        let wanted = asset_name()?;
        let asset = release
            .assets
            .iter()
            .find(|asset| asset.name == wanted)
            .ok_or_else(|| format!("no release asset named {wanted} in {RELEASE_REPO}"))?;

        let version_dir = format!("hmx-lsp-{}", release.version);
        let binary_path = format!("{version_dir}/{wanted}");

        if !fs::metadata(&binary_path).map_or(false, |stat| stat.is_file()) {
            zed::set_language_server_installation_status(
                language_server_id,
                &zed::LanguageServerInstallationStatus::Downloading,
            );
            fs::create_dir_all(&version_dir)
                .map_err(|err| format!("failed to create {version_dir}: {err}"))?;
            zed::download_file(&asset.download_url, &binary_path, DownloadedFileType::Uncompressed)?;
            zed::make_file_executable(&binary_path)?;

            if let Ok(entries) = fs::read_dir(".") {
                for entry in entries.flatten() {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if name.starts_with("hmx-lsp-") && name != version_dir {
                        let _ = fs::remove_dir_all(entry.path());
                    }
                }
            }
        }

        self.cached_path = Some(binary_path.clone());
        Ok(binary_path)
    }
}

impl zed::Extension for HmxExtension {
    fn new() -> Self {
        Self { cached_path: None }
    }

    fn language_server_command(
        &mut self,
        language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Command> {
        if let Some(command) = self.configured_binary(language_server_id, worktree) {
            return Ok(command);
        }
        if let Some(command) = self.from_environment(worktree) {
            return Ok(command);
        }
        if let Some(command) = self.from_path(worktree) {
            return Ok(command);
        }

        let downloaded = self.download(language_server_id)?;
        Ok(Command {
            command: downloaded,
            args: vec!["serve".to_string()],
            env: Default::default(),
        })
    }
}

zed::register_extension!(HmxExtension);
