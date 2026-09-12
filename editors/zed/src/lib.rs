use zed_extension_api::{self as zed, Command, LanguageServerId, Result};

struct HmxExtension;

impl zed::Extension for HmxExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &LanguageServerId,
        _worktree: &zed::Worktree,
    ) -> Result<Command> {
        Ok(Command {
            command: "/opt/conda/envs/hmx/bin/python".to_string(),
            args: vec!["-m".to_string(), "hmx_ls.server".to_string()],
            env: Default::default(),
        })
    }
}

zed::register_extension!(HmxExtension);
