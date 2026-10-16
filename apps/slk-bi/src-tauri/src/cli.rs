use serde_json::{json, Value};
use std::path::PathBuf;

pub fn execute(args: &[String]) -> Option<Result<Value, String>> {
    let first = args.first()?.as_str();
    if !matches!(
        first,
        "--bi-preview"
            | "--bi-register"
            | "--bi-archive"
            | "--bi-read"
            | "--bi-list"
            | "--help"
            | "-h"
            | "--version"
            | "-V"
    ) {
        return None;
    }
    Some((|| {
        if matches!(first, "--version" | "-V") {
            return Ok(json!({"bi_version":env!("CARGO_PKG_VERSION")}));
        }
        if matches!(first, "--help" | "-h") {
            return Ok(json!({"usage":[
            "slk-bi-desktop --bi-register <record.md> --project-id <id> --project-name <name>",
            "slk-bi-desktop --bi-read <run-id>", "slk-bi-desktop --bi-archive <run-id>",
            "slk-bi-desktop --bi-preview <record.md> --project-id <id> --project-name <name> (read-only, no registration)",
            "slk-bi-desktop --bi-list", "Optional: --config <BI source config path> (isolated tests)",
            "Registration/archive use native CODEX_THREAD_ID; no caller identity argument. Engineering source is read-only."]}));
        }
        let option = |name: &str| {
            args.iter()
                .position(|v| v == name)
                .and_then(|i| args.get(i + 1))
        };
        let config = if let Some(path) = option("--config") {
            PathBuf::from(path)
        } else {
            crate::commands::default_path()?
        };
        let registry = config.with_file_name("bi-sources");
        if first == "--bi-list" {
            return crate::commands::runs_from(&config, None);
        }
        let value = args
            .get(1)
            .filter(|v| !v.starts_with("--"))
            .ok_or("SLK_BI_ARGUMENT_REQUIRED")?;
        match first {
            "--bi-preview" => crate::sources::project_markdown(
                &std::fs::read_to_string(value).map_err(|e| e.to_string())?,
                option("--project-id").ok_or("SLK_BI_PROJECT_REQUIRED")?,
                option("--project-name").ok_or("SLK_BI_PROJECT_REQUIRED")?,
            ),
            "--bi-read" => crate::commands::run_from(&config, value, "run"),
            "--bi-archive" => {
                crate::sources::archive(&registry, value, &crate::sources::native_caller()?)
            }
            _ => crate::sources::register(
                &registry,
                &PathBuf::from(value),
                option("--project-id").ok_or("SLK_BI_PROJECT_REQUIRED")?,
                option("--project-name").ok_or("SLK_BI_PROJECT_REQUIRED")?,
                &crate::sources::native_caller()?,
            ),
        }
    })())
}
