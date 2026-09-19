use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContentionKind {
    BuildDirectory,
    PackageCache,
    WindowsTargetSharing,
}

impl ContentionKind {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::BuildDirectory => "build-directory-lock",
            Self::PackageCache => "package-cache-lock",
            Self::WindowsTargetSharing => "windows-target-sharing",
        }
    }
}

pub fn classify_contention(output: &str, run_target: &Path) -> Option<ContentionKind> {
    let lower = output.to_ascii_lowercase();
    if lower.contains("blocking waiting for file lock on build directory") {
        return Some(ContentionKind::BuildDirectory);
    }
    if lower.contains("blocking waiting for file lock on package cache") {
        return Some(ContentionKind::PackageCache);
    }
    let normalized_output = lower.replace('\\', "/");
    let normalized_target = run_target
        .display()
        .to_string()
        .to_ascii_lowercase()
        .replace('\\', "/");
    let sharing_error = normalized_output.contains("os error 32")
        || normalized_output.contains("being used by another process");
    if sharing_error
        && !normalized_target.is_empty()
        && normalized_output.contains(&normalized_target)
    {
        return Some(ContentionKind::WindowsTargetSharing);
    }
    None
}
