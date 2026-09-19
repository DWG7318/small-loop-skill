use std::ffi::{OsStr, OsString};
use std::path::Path;

use slk_cargo::{parse_cli, CargoInvocation, CliCommand, RunPaths};
use tempfile::tempdir;

fn values(items: &[&str]) -> Vec<OsString> {
    items.iter().map(OsString::from).collect()
}

#[test]
fn run_paths_are_stable_inside_one_run_and_separate_across_runs() {
    let data_root = tempdir().unwrap();
    let run_a = RunPaths::new(data_root.path(), "project-a", "run-001").unwrap();
    let same_run = RunPaths::new(data_root.path(), "project-a", "run-001").unwrap();
    let run_b = RunPaths::new(data_root.path(), "project-a", "run-002").unwrap();

    let expected = data_root
        .path()
        .join("runtime/cargo/project-a/run-001/primary");
    assert_eq!(run_a.primary_target(), expected);
    assert_eq!(run_a.primary_target(), same_run.primary_target());
    assert_ne!(run_a.primary_target(), run_b.primary_target());
    assert_eq!(run_a.run_root(), expected.parent().unwrap());
    assert_eq!(run_a.cleanup_root(), run_a.run_root());
}

#[test]
fn project_and_run_ids_must_be_safe_single_path_segments() {
    let data_root = tempdir().unwrap();
    for invalid in ["", ".", "..", "a/b", r"a\b", "with space", "é"] {
        assert!(RunPaths::new(data_root.path(), invalid, "run-001").is_err());
        assert!(RunPaths::new(data_root.path(), "project-a", invalid).is_err());
    }
    assert!(RunPaths::new(data_root.path(), "project_a.2", "RUN-2026_09").is_ok());
}

#[test]
fn cargo_invocation_preserves_program_and_arguments_in_order() {
    let arguments = values(&["test", "-p", "demo", "--release", "--", "--nocapture"]);
    let invocation = CargoInvocation::new("cargo", arguments.clone(), None).unwrap();

    assert_eq!(invocation.program(), OsStr::new("cargo"));
    assert_eq!(invocation.arguments(), arguments.as_slice());
}

#[test]
fn explicit_target_overrides_are_rejected_before_execution() {
    for arguments in [
        values(&["test", "--target-dir", "somewhere"]),
        values(&["test", "--target-dir=somewhere"]),
    ] {
        let error = CargoInvocation::new("cargo", arguments, None).unwrap_err();
        assert_eq!(error.code(), "SLK_CARGO_TARGET_OVERRIDE");
    }

    let error = CargoInvocation::new(
        "cargo",
        values(&["test"]),
        Some(OsStr::new(r"D:\shared-target")),
    )
    .unwrap_err();
    assert_eq!(error.code(), "SLK_CARGO_TARGET_OVERRIDE");
}

#[test]
fn cleanup_scope_is_the_exact_run_subtree() {
    let data_root = Path::new(r"D:\SLK-DATA");
    let current = RunPaths::new(data_root, "project-a", "run-001").unwrap();
    let sibling = RunPaths::new(data_root, "project-a", "run-002").unwrap();

    assert_eq!(
        current.cleanup_root(),
        data_root.join("runtime/cargo/project-a/run-001")
    );
    assert!(!sibling.run_root().starts_with(current.cleanup_root()));
    assert!(!current
        .cleanup_root()
        .starts_with(data_root.join("cargo-home")));
}

#[test]
fn cli_parses_run_and_cleanup_without_consuming_cargo_arguments() {
    let run = parse_cli(values(&[
        "run",
        "--data-root",
        r"D:\SLK-DATA",
        "--project-id",
        "project-a",
        "--run-id",
        "run-001",
        "--cargo-program",
        "cargo-nextest",
        "--",
        "test",
        "--workspace",
        "--",
        "--nocapture",
    ]))
    .unwrap();
    match run {
        CliCommand::Run(command) => {
            assert_eq!(command.data_root(), Some(Path::new(r"D:\SLK-DATA")));
            assert_eq!(command.project_id(), "project-a");
            assert_eq!(command.run_id(), "run-001");
            assert_eq!(command.cargo_program(), OsStr::new("cargo-nextest"));
            assert_eq!(
                command.cargo_arguments(),
                values(&["test", "--workspace", "--", "--nocapture"])
            );
        }
        CliCommand::Cleanup(_) => panic!("expected run command"),
    }

    let cleanup = parse_cli(values(&[
        "cleanup",
        "--project-id",
        "project-a",
        "--run-id",
        "run-001",
    ]))
    .unwrap();
    assert!(matches!(cleanup, CliCommand::Cleanup(_)));
}

#[test]
fn cli_rejects_missing_delimiter_or_missing_cargo_command() {
    for arguments in [
        values(&[
            "run",
            "--project-id",
            "project-a",
            "--run-id",
            "run-001",
            "test",
        ]),
        values(&[
            "run",
            "--project-id",
            "project-a",
            "--run-id",
            "run-001",
            "--",
        ]),
    ] {
        assert_eq!(parse_cli(arguments).unwrap_err().code(), "SLK_CARGO_USAGE");
    }
}
