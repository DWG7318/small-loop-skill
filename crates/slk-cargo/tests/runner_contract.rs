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
import subprocess
import sys
import time

mode = sys.argv[1]
marker = pathlib.Path(sys.argv[2])
target = os.environ["CARGO_TARGET_DIR"]
print("OUT target=" + target, flush=True)

if mode == "ordinary":
    print("ERR ordinary failure", file=sys.stderr, flush=True)
    raise SystemExit(7)

if mode == "hold-child":
    marker.write_text(str(os.getpid()), encoding="ascii")
    deadline = time.monotonic() + 8
    with marker.with_suffix(".alive").open("a", encoding="ascii") as writer:
        while time.monotonic() < deadline and not marker.with_suffix(".stop").exists():
            writer.write(str(time.monotonic()) + "\n")
            writer.flush()
            time.sleep(0.02)
    marker.with_suffix(".done").write_text("done", encoding="ascii")
    raise SystemExit(0)

if mode in ("exit-parent-0", "exit-parent-7"):
    subprocess.Popen([sys.executable, __file__, "hold-descendant", str(marker)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000 if os.name == "nt" else 0)
    raise SystemExit(int(mode.rsplit("-", 1)[1]))

if mode == "hold-descendant":
    marker.write_text(str(os.getpid()), encoding="ascii")
    with (pathlib.Path(target) / "descendant-writer.txt").open("a", encoding="ascii") as writer:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not marker.with_suffix(".stop").exists():
            writer.write(str(time.monotonic()) + "\n")
            writer.flush()
            marker.with_suffix(".alive").write_text(str(time.monotonic()), encoding="ascii")
            time.sleep(0.02)
    marker.with_suffix(".done").write_text("done", encoding="ascii")
    raise SystemExit(0)

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

#[cfg(windows)]
#[test]
fn windows_cargo_child_receives_plain_spelling_for_the_same_verbatim_run_target() {
    let root = tempdir().unwrap();
    let verbatim_root = root.path().canonicalize().unwrap();
    assert!(verbatim_root
        .as_os_str()
        .to_string_lossy()
        .starts_with(r"\\?\"));
    let paths = RunPaths::new(&verbatim_root, "project-a", "run-verbatim").unwrap();
    let script = fake_cargo_script(root.path());
    let marker = root.path().join("verbatim.marker");
    let mut capture = Capture::default();

    let result = run_cargo(
        &invocation(&script, "capture", &marker),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();

    assert!(result.success());
    assert!(paths
        .primary_target()
        .as_os_str()
        .to_string_lossy()
        .starts_with(r"\\?\"));
    let child_target = fs::read_to_string(marker).unwrap();
    assert!(!child_target.starts_with(r"\\?\"));
    assert_eq!(
        Path::new(&child_target).canonicalize().unwrap(),
        paths.primary_target().canonicalize().unwrap()
    );
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

#[test]
fn crashed_wrapper_leaves_exact_child_evidence_and_does_not_allow_cleanup() {
    use std::time::Instant;
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-crash").unwrap();
    let script = fake_cargo_script(root.path());
    let marker = root.path().join("child.marker");
    let mut command = Command::new(env!("CARGO_BIN_EXE_slk-cargo"));
    command
        .args(["run", "--data-root"])
        .arg(root.path())
        .args([
            "--project-id",
            "project-a",
            "--run-id",
            "run-crash",
            "--cargo-program",
            "python",
            "--",
        ])
        .arg(&script)
        .arg("hold-child")
        .arg(&marker)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut wrapper = command.spawn().unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !marker.with_extension("alive").exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    let was_alive = marker.with_extension("alive").exists();
    wrapper.kill().unwrap();
    wrapper.wait().unwrap();
    let before = fs::metadata(marker.with_extension("alive"))
        .map(|m| m.len())
        .unwrap_or(0);
    let deadline = Instant::now() + Duration::from_secs(5);
    let after = loop {
        let size = fs::metadata(marker.with_extension("alive"))
            .map(|m| m.len())
            .unwrap_or(0);
        if size > before || Instant::now() >= deadline {
            break size;
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    let child_pid = fs::read_to_string(&marker).unwrap_or_default();
    let lease = fs::read_dir(paths.run_root().join("leases"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let records: Vec<serde_json::Value> = fs::read_to_string(&lease)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let cleanup_error = slk_cargo::cleanup_run(&paths).unwrap_err();
    // Signal only this fixture's child to finish, including on failed assertions.
    fs::write(marker.with_extension("stop"), b"stop").unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !marker.with_extension("done").exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        was_alive && after > before,
        "child must actually remain active after wrapper exit"
    );
    assert_eq!(cleanup_error.code(), "SLK_CARGO_CLEANUP_UNRESOLVED");
    assert!(lease.is_file());
    let native = records
        .iter()
        .find(|entry| entry["schema_version"] == "slk.cargo-native-process/v1")
        .unwrap();
    assert_eq!(
        native["process"]["pid"],
        child_pid.trim().parse::<u32>().unwrap()
    );
    assert!(native["process"]["creation_time"]
        .as_str()
        .unwrap()
        .contains(':'));
    assert_eq!(
        native["target"],
        paths.primary_target().to_string_lossy().as_ref()
    );
    assert!(marker.with_extension("done").exists());
}

fn assert_exited_native_parent_keeps_cleanup_unresolved(exit_code: i32) {
    use std::time::Instant;
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-descendant").unwrap();
    let script = fake_cargo_script(root.path());
    let marker = root.path().join("descendant.marker");
    let mut capture = Capture::default();
    let result = run_cargo(
        &invocation(&script, &format!("exit-parent-{exit_code}"), &marker),
        &paths,
        &quick_config(),
        &mut capture,
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !marker.with_extension("alive").exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    let target_writer = paths.primary_target().join("descendant-writer.txt");
    let before = fs::metadata(&target_writer).map(|m| m.len()).unwrap_or(0);
    std::thread::sleep(Duration::from_millis(100));
    let after = fs::metadata(&target_writer).map(|m| m.len()).unwrap_or(0);
    let cleanup = slk_cargo::cleanup_run(&paths);
    // Stop only this exact fixture before assertions, even on the old unsafe path.
    fs::write(marker.with_extension("stop"), b"stop").unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !marker.with_extension("done").exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(result.exit_code(), Some(exit_code));
    assert_eq!(result.attempts(), 1);
    assert!(
        before > 0 && after > before,
        "native parent's descendant must really write after parent exit"
    );
    assert!(marker.with_extension("done").exists());
    assert_eq!(cleanup.unwrap_err().code(), "SLK_CARGO_CLEANUP_UNRESOLVED");
    assert!(target_writer.is_file());
    assert_eq!(
        fs::read_dir(paths.run_root().join("leases"))
            .unwrap()
            .count(),
        1
    );
}

#[test]
fn successful_native_parent_exit_does_not_prove_descendant_writers_stopped() {
    assert_exited_native_parent_keeps_cleanup_unresolved(0);
}

#[test]
fn failed_native_parent_exit_does_not_prove_descendant_writers_stopped() {
    assert_exited_native_parent_keeps_cleanup_unresolved(7);
}

#[test]
fn spawn_failure_does_not_leave_an_unowned_native_lease() {
    let root = tempdir().unwrap();
    let paths = RunPaths::new(root.path(), "project-a", "run-no-spawn").unwrap();
    let missing = CargoInvocation::new(
        root.path().join("missing-cargo.exe"),
        vec!["check".into()],
        None,
    )
    .unwrap();
    let error = run_cargo(&missing, &paths, &quick_config(), &mut Capture::default()).unwrap_err();
    assert_eq!(error.code(), "SLK_CARGO_SPAWN");
    assert!(slk_cargo::cleanup_run(&paths).unwrap());
}
