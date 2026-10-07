pub mod commands;

use std::ffi::OsStr;

fn should_launch_interface<I, S>(arguments: I) -> bool
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    !arguments.into_iter().any(|argument| {
        matches!(
            argument.as_ref().to_str(),
            Some("--help" | "-h" | "--version" | "-V")
        )
    })
}

#[cfg(target_os = "windows")]
mod single_instance {
    use std::ptr;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    const INSTANCE_NAME: &str = "Local\\com.dwg7318.slk.bi.single-instance";

    pub struct Guard(HANDLE);

    impl Drop for Guard {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }

    fn acquire_named(instance_name: &str) -> Result<Option<Guard>, u32> {
        let name: Vec<u16> = format!("{instance_name}\0").encode_utf16().collect();
        let handle = unsafe { CreateMutexW(ptr::null(), 0, name.as_ptr()) };
        if handle.is_null() {
            return Err(unsafe { GetLastError() });
        }
        if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
            unsafe { CloseHandle(handle) };
            return Ok(None);
        }
        Ok(Some(Guard(handle)))
    }

    pub fn acquire() -> Result<Option<Guard>, u32> {
        acquire_named(INSTANCE_NAME)
    }

    #[cfg(test)]
    mod tests {
        use super::acquire_named;

        #[test]
        fn named_guard_rejects_a_second_process_identity_until_release() {
            let test_name = format!(
                "Local\\com.dwg7318.slk.bi.single-instance.test.{}.{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .expect("system time must be after the epoch")
                    .as_nanos()
            );
            let first = acquire_named(&test_name).expect("first mutex request must succeed");
            assert!(first.is_some());
            let second =
                acquire_named(&test_name).expect("second mutex request must be observable");
            assert!(second.is_none());
            drop(first);
            assert!(acquire_named(&test_name)
                .expect("released mutex must be reusable")
                .is_some());
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if !should_launch_interface(std::env::args_os().skip(1)) {
        return;
    }

    #[cfg(target_os = "windows")]
    let _single_instance = match single_instance::acquire() {
        Ok(Some(guard)) => guard,
        Ok(None) => return,
        Err(code) => panic!("SLK BI single-instance guard failed: {code}"),
    };

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::metadata,
            commands::sync_webbi,
            commands::projects,
            commands::runs,
            commands::run,
            commands::graph,
            commands::roles,
            commands::plans,
            commands::events,
            commands::evidence
        ])
        .run(tauri::generate_context!())
        .expect("SLK BI failed to start");
}

#[cfg(test)]
mod startup_argument_tests {
    use super::should_launch_interface;

    #[test]
    fn help_and_version_probes_exit_without_creating_a_window() {
        for argument in ["--help", "-h", "--version", "-V"] {
            assert!(!should_launch_interface([argument]));
        }
        assert!(should_launch_interface(std::iter::empty::<&str>()));
    }
}
