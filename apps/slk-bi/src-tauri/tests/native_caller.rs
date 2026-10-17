//! Child-process environment fixtures exercise selection rules, not a fake production host.
//! Every source and registry is temporary; the parent process identity is never altered.
use std::{fs, path::Path, process::Command};

fn record(root: &Path, creator: &str) -> std::path::PathBuf {
    let path = root.join("record.md");
    fs::write(&path, format!("# SLK Run — CALLER-FIXTURE\n\n## Run 定义\n- 创建Supervisor：{creator}\n- SLK版本：3.1.1\n\n## 当前摘要（唯一，按事实更新）\n- 当前状态：CLOSED / D2 PASS\n\n## GO 与 CELL 计划\n- 1：隔离验证\n")).unwrap();
    path
}

fn command(root: &Path, thread: Option<&str>, legacy_session: Option<&str>) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_slk-bi-desktop"));
    command
        .current_dir(root)
        .env_remove("CODEX_THREAD_ID")
        .env_remove("CODEX_SESSION_ID");
    if let Some(id) = thread {
        command.env("CODEX_THREAD_ID", id);
    }
    if let Some(id) = legacy_session {
        command.env("CODEX_SESSION_ID", id);
    }
    command
}

#[test]
fn native_cli_prefers_current_thread_over_inherited_root_session() {
    let root = tempfile::tempdir().unwrap();
    let source = record(root.path(), "fixture-current-thread");
    let result = command(
        root.path(),
        Some("fixture-current-thread"),
        Some("fixture-root-session"),
    )
    .arg("--bi-register")
    .arg(&source)
    .args(["--project-id", "p", "--project-name", "P", "--config"])
    .arg(root.path().join("config.json"))
    .output()
    .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let registered: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(
        registered["creator_supervisor_id"],
        "fixture-current-thread"
    );
    let refused = command(
        root.path(),
        Some("fixture-other-thread"),
        Some("fixture-current-thread"),
    )
    .args(["--bi-archive", "CALLER-FIXTURE", "--config"])
    .arg(root.path().join("config.json"))
    .output()
    .unwrap();
    assert!(!refused.status.success());
    assert!(String::from_utf8_lossy(&refused.stderr).contains("SLK_BI_CREATOR_REQUIRED"));
}

#[test]
fn native_cli_uses_legacy_session_only_as_fallback() {
    let root = tempfile::tempdir().unwrap();
    let source = record(root.path(), "fixture-legacy-session");
    let result = command(root.path(), Some("  "), Some("fixture-legacy-session"))
        .arg("--bi-register")
        .arg(source)
        .args(["--project-id", "p", "--project-name", "P", "--config"])
        .arg(root.path().join("config.json"))
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn native_cli_rejects_missing_host_generic_identity_flags_and_wrong_creator() {
    let root = tempfile::tempdir().unwrap();
    let source = record(root.path(), "fixture-owner");
    let registration = |thread| {
        let mut child = command(root.path(), thread, None);
        child
            .arg("--bi-register")
            .arg(&source)
            .args(["--project-id", "p", "--project-name", "P", "--config"])
            .arg(root.path().join("config.json"));
        child
    };
    let missing = registration(None)
        .env("SLK_BI_SUPERVISOR", "fixture-owner")
        .output()
        .unwrap();
    assert!(!missing.status.success());
    assert!(String::from_utf8_lossy(&missing.stderr).contains("SLK_BI_NATIVE_CALLER_MISSING"));
    let flagged = registration(None)
        .args(["--supervisor", "fixture-owner"])
        .output()
        .unwrap();
    assert!(!flagged.status.success());
    assert!(String::from_utf8_lossy(&flagged.stderr).contains("SLK_BI_CALLER_ARGUMENT_UNSUPPORTED"));
    let wrong = registration(Some("fixture-not-owner")).output().unwrap();
    assert!(!wrong.status.success());
    assert!(String::from_utf8_lossy(&wrong.stderr).contains("SLK_BI_CREATOR_REQUIRED"));
    assert!(!root.path().join("bi-sources").exists());
}
