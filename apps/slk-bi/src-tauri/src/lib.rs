pub mod commands;

#[cfg(target_os = "windows")]
mod single_instance {
    use std::ptr;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    pub struct Guard(HANDLE);

    impl Drop for Guard {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }

    pub fn acquire() -> Result<Option<Guard>, u32> {
        let name: Vec<u16> = "Local\\com.dwg7318.slk.bi.single-instance\0"
            .encode_utf16()
            .collect();
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

    #[cfg(test)]
    mod tests {
        use super::acquire;

        #[test]
        fn named_guard_rejects_a_second_process_identity_until_release() {
            let first = acquire().expect("first mutex request must succeed");
            assert!(first.is_some());
            let second = acquire().expect("second mutex request must be observable");
            assert!(second.is_none());
            drop(first);
            assert!(acquire()
                .expect("released mutex must be reusable")
                .is_some());
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
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
