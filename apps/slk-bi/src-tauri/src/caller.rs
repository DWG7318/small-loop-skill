//! Host adapters supply identity. Arbitrary CLI flags or generic environment variables
//! are deliberately not an authentication interface.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallerIdentity {
    pub runtime: String,
    pub host: String,
    pub session: String,
}

pub trait CallerHost {
    fn current(&self) -> Result<CallerIdentity, String>;
}

pub struct CodexHost;
impl CallerHost for CodexHost {
    fn current(&self) -> Result<CallerIdentity, String> {
        let nonempty = |name| std::env::var(name).ok().filter(|s| !s.trim().is_empty());
        let thread = nonempty("CODEX_THREAD_ID");
        let session = nonempty("CODEX_SESSION_ID");
        // A child thread may inherit its root's legacy session ID. The current
        // native thread is authoritative; session is only a legacy fallback.
        Ok(CallerIdentity {
            runtime: "codex".into(),
            host: "codex-native".into(),
            session: thread.or(session).ok_or(
                "SLK_BI_NATIVE_CALLER_MISSING: this platform has no supported trusted host adapter",
            )?,
        })
    }
}

pub fn creator_session(host: &impl CallerHost) -> Result<String, String> {
    let caller = host.current()?;
    if caller.runtime.is_empty() || caller.host.is_empty() || caller.session.is_empty() {
        return Err("SLK_BI_CALLER_ID_INVALID".into());
    }
    Ok(caller.session)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fake_host_only_proves_the_interface_and_preserves_legacy_session_ids() {
        struct FakeHost;
        impl CallerHost for FakeHost {
            fn current(&self) -> Result<CallerIdentity, String> {
                Ok(CallerIdentity {
                    runtime: "unit-test-only".into(),
                    host: "fake-host".into(),
                    session: "legacy-supervisor".into(),
                })
            }
        }
        assert_eq!(creator_session(&FakeHost).unwrap(), "legacy-supervisor");
    }
}
