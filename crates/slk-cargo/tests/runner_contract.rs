use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::Duration;

use slk_cargo::{
    classify_contention, run_cargo, CargoInvocation, ContentionKind, OutputSink, RunPaths,
    RunnerConfig,
};
use tempfile::tempdir;

#[derive(Default)]
struct Capture {
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

impl OutputSink for Capture {
    fn stdout(&mut self, bytes: &[u8]) {
        self.stdout.extend_from_slice(bytes);
    }

    fn stderr(&mut self, bytes: &[u8]) {
        self.stderr.extend_from_slice(bytes);
    }
}

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).replace("\\", "/")
}

fn fake_cargo_script(root: &Path) -> std::path::PathBuf {
    let path = root.join("fake_cargo.py");
    fs::write(
        &path,
        r#"import os
import pathlib
import sys
import time

mode = sys.argv[1]
marker = pathlib.Path(sys.argv[2])
target = os.environ["CARGO_TARGET_DIR"]
print("OUT target=" + target, flush=True)

if mode == "ordinary":
    print("ERR ordinary failure", file=sys.stderr, flush=True)
    raise SystemExit(7)

if mode == "windows-sharing":
    print("failed inside " + target + ": process cannot access the file because it is being used by another process. (os error 32)", file=sys.stderr, flush=True)
    raise SystemExit(1)

first = not marker.exists()
if first:
    marker.write_text(target, encoding="utf-8")

if mode == "package-once" and first:
    print("Blocking waiting for file lock on package cache", file=sys.stderr, flush=True)
    time.sleep(5)
elif mode == "build-once" and first:
    print("Blocking waiting for file lock on build directory", file=sys.stderr, flush=True)
    time.sleep(5)
elif mode == "build-always":
    print("Blocking waiting for file lock on build directory", file=sys.stderr, flush=True)
    time.sleep(5)
else:
    print("retry-ok", flush=True)
"#,
    )
    .unwrap();
    path
}

fn invocation(script: &Path, mode: &str, marker: &Path) -> CargoInvocation {
    CargoInvocation::new(
        "python",
        vec![
            script.as_os_str().to_owned(),
            OsString::from(mode),
            marker.as_os_str().to_owned(),
        ],
        None,
    )
    .unwrap()
}

fn quick_config() -> RunnerConfig {
    RunnerConfig::new(Duration::from_millis(80))
}

#[test]
fn classification_requires_explicit_contention_evidence() {
    let target = Path::new(r"D:\SLK\runtime\cargo\p\r\primary");
    assert_eq!(
        classify_contention("Blocking waiting for file lock on build directory", target),
        Some(ContentionKind::BuildDirectory)
    );
    assert_eq!(
        classify_contention("Blocking waiting for file lock on package cache", target),
        Some(ContentionKind::PackageCache)
    );
    assert_eq!(
        classify_contention(
            &format!(
                "failed in {}: process cannot access the file because it is being used by another process. (os error 32)",
                target.display()
            ),
            target,
        ),
        Some(ContentionKind::WindowsTargetSharing)
    );
    assert_eq!(
        classify_contention(
            "process cannot access the file because it is being used by another process. (os error 32)",
            target,
        ),
        None
    );
    assert_eq!(classify_contention("quiet for 120 seconds", target), None);
    assert_eq!(classify_contention("ordinary compiler error", target), None);
}

#[test]
fn ordinary_failure_streams_output_and_preserves_exit_code() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-001").unwrap();
    let script = fake_cargo_script(root.path());
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(&script, "ordinary", &root.path().join("ordinary.marker")),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert_eq!(result.exit_code(), Some(7));
    assert_eq!(result.attempts(), 1);
    assert!(!result.recovered());
    assert!(text(&capture.stdout).contains("OUT target="));
    assert!(text(&capture.stderr).contains("ERR ordinary failure"));
}

#[test]
fn package_cache_wait_is_bounded_and_retries_same_target_once() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-package").unwrap();
    let script = fake_cargo_script(root.path());
    let marker = root.path().join("package.marker");
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(&script, "package-once", &marker),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert_eq!(result.exit_code(), Some(0));
    assert_eq!(result.attempts(), 2);
    assert!(result.recovered());
    assert_eq!(result.final_target(), paths.primary_target());
    assert_eq!(
        fs::read_to_string(marker).unwrap(),
        paths.primary_target().display().to_string()
    );
    assert!(text(&capture.stderr).contains("SLK_CARGO_RESOURCE_WAIT"));
}

#[test]
fn build_lock_retries_once_in_a_fresh_recovery_target() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-build").unwrap();
    let script = fake_cargo_script(root.path());
    let marker = root.path().join("build.marker");
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(&script, "build-once", &marker),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert_eq!(result.exit_code(), Some(0));
    assert_eq!(result.attempts(), 2);
    assert!(result.recovered());
    assert_eq!(result.final_target(), paths.recovery_target(1));
    assert_ne!(
        fs::read_to_string(marker).unwrap(),
        result.final_target().display().to_string()
    );
}

#[test]
fn a_second_lock_failure_stops_without_an_unbounded_loop() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-twice").unwrap();
    let script = fake_cargo_script(root.path());
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(&script, "build-always", &root.path().join("always.marker")),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert_eq!(result.attempts(), 2);
    assert!(!result.success());
    assert_eq!(result.contention(), Some(ContentionKind::BuildDirectory));
}

#[test]
fn windows_target_sharing_retries_with_a_recovery_target() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-sharing").unwrap();
    let script = fake_cargo_script(root.path());
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(
            &script,
            "windows-sharing",
            &root.path().join("sharing.marker"),
        ),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert_eq!(result.attempts(), 2);
    assert_eq!(result.final_target(), paths.recovery_target(1));
    assert_eq!(
        result.contention(),
        Some(ContentionKind::WindowsTargetSharing)
    );
}

#[test]
fn runner_does_not_terminate_unrelated_processes() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-unrelated").unwrap();
    let script = fake_cargo_script(root.path());
    let mut unrelated = Command::new("python")
        .args(["-c", "import time; time.sleep(5)"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut capture = Capture::default();

    let _ = run_cargo(
        &invocation(&script, "build-once", &root.path().join("unrelated.marker")),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert!(unrelated.try_wait().unwrap().is_none());
    unrelated.kill().unwrap();
    unrelated.wait().unwrap();
}
