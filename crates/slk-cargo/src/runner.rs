use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

use crate::{classify_contention, CargoGuardError, CargoInvocation, ContentionKind, RunPaths};

pub trait OutputSink {
    fn stdout(&mut self, bytes: &[u8]);
    fn stderr(&mut self, bytes: &[u8]);
}

#[derive(Debug, Clone, Copy)]
pub struct RunnerConfig {
    contention_wait: Duration,
}

impl RunnerConfig {
    pub fn new(contention_wait: Duration) -> Self {
        Self { contention_wait }
    }

    pub fn default_for_cli() -> Self {
        Self::new(Duration::from_secs(15))
    }
}

#[derive(Debug, Clone)]
pub struct CargoRunResult {
    exit_code: Option<i32>,
    attempts: u32,
    recovered: bool,
    contention: Option<ContentionKind>,
    final_target: PathBuf,
}

impl CargoRunResult {
    pub fn exit_code(&self) -> Option<i32> {
        self.exit_code
    }

    pub fn attempts(&self) -> u32 {
        self.attempts
    }

    pub fn recovered(&self) -> bool {
        self.recovered
    }

    pub fn contention(&self) -> Option<ContentionKind> {
        self.contention
    }

    pub fn final_target(&self) -> &Path {
        &self.final_target
    }

    pub fn success(&self) -> bool {
        self.exit_code == Some(0)
    }
}

pub fn run_cargo(
    invocation: &CargoInvocation,
    paths: &RunPaths,
    config: &RunnerConfig,
    sink: &mut dyn OutputSink,
) -> Result<CargoRunResult, CargoGuardError> {
    let mut target = paths.primary_target();
    let mut observed_contention = None;

    for attempt in 1..=2 {
        fs::create_dir_all(&target).map_err(|error| {
            CargoGuardError::new(
                "SLK_CARGO_TARGET_CREATE",
                format!("{}: {error}", target.display()),
            )
        })?;
        let outcome = run_attempt(invocation, &target, config, sink)?;
        if observed_contention.is_none() {
            observed_contention = outcome.contention;
        }
        if outcome.status.as_ref().is_some_and(ExitStatus::success) {
            return Ok(CargoRunResult {
                exit_code: Some(0),
                attempts: attempt,
                recovered: observed_contention.is_some(),
                contention: observed_contention,
                final_target: target,
            });
        }

        let Some(kind) = outcome.contention else {
            return Ok(CargoRunResult {
                exit_code: outcome.status.and_then(|status| status.code()),
                attempts: attempt,
                recovered: false,
                contention: observed_contention,
                final_target: target,
            });
        };
        observed_contention.get_or_insert(kind);
        if attempt == 2 {
            return Ok(CargoRunResult {
                exit_code: outcome.status.and_then(|status| status.code()),
                attempts: attempt,
                recovered: false,
                contention: observed_contention,
                final_target: target,
            });
        }

        if matches!(
            kind,
            ContentionKind::BuildDirectory | ContentionKind::WindowsTargetSharing
        ) {
            target = paths.recovery_target(1);
        }
        sink.stderr(
            format!(
                "SLK_CARGO_RESOURCE_RETRY kind={} target={}\n",
                kind.label(),
                target.display()
            )
            .as_bytes(),
        );
    }
    unreachable!("attempt loop has a fixed non-empty range")
}

struct AttemptOutcome {
    status: Option<ExitStatus>,
    contention: Option<ContentionKind>,
}

enum StreamChunk {
    Stdout(Vec<u8>),
    Stderr(Vec<u8>),
}

fn run_attempt(
    invocation: &CargoInvocation,
    target: &Path,
    config: &RunnerConfig,
    sink: &mut dyn OutputSink,
) -> Result<AttemptOutcome, CargoGuardError> {
    let mut child = Command::new(invocation.program())
        .args(invocation.arguments())
        .env("CARGO_TARGET_DIR", target)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| CargoGuardError::new("SLK_CARGO_SPAWN", error.to_string()))?;

    let stdout = child.stdout.take().expect("piped child stdout");
    let stderr = child.stderr.take().expect("piped child stderr");
    let (sender, receiver) = mpsc::channel();
    let stdout_reader = spawn_reader(stdout, sender.clone(), true);
    let stderr_reader = spawn_reader(stderr, sender, false);
    let mut stderr_bytes = Vec::new();
    let mut contention = None;
    let mut deadline = None;
    let mut status = None;

    while status.is_none() {
        if let Ok(chunk) = receiver.recv_timeout(Duration::from_millis(10)) {
            forward_chunk(chunk, sink, &mut stderr_bytes);
            if contention.is_none() {
                contention = classify_contention(&String::from_utf8_lossy(&stderr_bytes), target);
                if let Some(kind) = contention {
                    deadline = Some(Instant::now() + config.contention_wait);
                    sink.stderr(
                        format!(
                            "SLK_CARGO_RESOURCE_WAIT kind={} max_ms={}\n",
                            kind.label(),
                            config.contention_wait.as_millis()
                        )
                        .as_bytes(),
                    );
                }
            }
        }

        status = child
            .try_wait()
            .map_err(|error| CargoGuardError::new("SLK_CARGO_WAIT", error.to_string()))?;
        if status.is_none() && deadline.is_some_and(|value| Instant::now() >= value) {
            child.kill().map_err(|error| {
                CargoGuardError::new("SLK_CARGO_KILL_OWN_CHILD", error.to_string())
            })?;
            child
                .wait()
                .map_err(|error| CargoGuardError::new("SLK_CARGO_WAIT", error.to_string()))?;
            status = None;
            break;
        }
    }

    stdout_reader
        .join()
        .map_err(|_| CargoGuardError::new("SLK_CARGO_IO", "stdout reader panicked"))??;
    stderr_reader
        .join()
        .map_err(|_| CargoGuardError::new("SLK_CARGO_IO", "stderr reader panicked"))??;
    drain_chunks(&receiver, sink, &mut stderr_bytes);
    if contention.is_none() {
        contention = classify_contention(&String::from_utf8_lossy(&stderr_bytes), target);
    }
    Ok(AttemptOutcome { status, contention })
}

fn spawn_reader<R: Read + Send + 'static>(
    mut reader: R,
    sender: mpsc::Sender<StreamChunk>,
    stdout: bool,
) -> thread::JoinHandle<Result<(), CargoGuardError>> {
    thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        loop {
            let count = reader
                .read(&mut buffer)
                .map_err(|error| CargoGuardError::new("SLK_CARGO_IO", error.to_string()))?;
            if count == 0 {
                return Ok(());
            }
            let bytes = buffer[..count].to_vec();
            let chunk = if stdout {
                StreamChunk::Stdout(bytes)
            } else {
                StreamChunk::Stderr(bytes)
            };
            if sender.send(chunk).is_err() {
                return Ok(());
            }
        }
    })
}

fn drain_chunks(
    receiver: &Receiver<StreamChunk>,
    sink: &mut dyn OutputSink,
    stderr_bytes: &mut Vec<u8>,
) {
    while let Ok(chunk) = receiver.try_recv() {
        forward_chunk(chunk, sink, stderr_bytes);
    }
}

fn forward_chunk(chunk: StreamChunk, sink: &mut dyn OutputSink, stderr_bytes: &mut Vec<u8>) {
    match chunk {
        StreamChunk::Stdout(bytes) => sink.stdout(&bytes),
        StreamChunk::Stderr(bytes) => {
            stderr_bytes.write_all(&bytes).expect("write to Vec");
            sink.stderr(&bytes);
        }
    }
}
