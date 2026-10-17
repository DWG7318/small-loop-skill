//! BI-private configuration and pending uploads. Never engineering state.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs, io::Write, path::Path};

pub fn hash(value: &Value) -> Result<String, String> {
    let mut canonical = value.clone();
    canonical.sort_all_objects();
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&canonical).map_err(|_| "SLK_WEBBI_JSON_INVALID")?)
    ))
}

pub fn atomic_write(path: &Path, value: &Value) -> Result<(), String> {
    let parent = path.parent().ok_or("SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    fs::create_dir_all(parent).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    let mut file =
        tempfile::NamedTempFile::new_in(parent).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    file.write_all(&serde_json::to_vec(value).map_err(|_| "SLK_WEBBI_JSON_INVALID")?)
        .map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    file.as_file()
        .sync_all()
        .map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    file.persist(path)
        .map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    Ok(())
}

pub fn read(path: &Path) -> Result<Value, String> {
    serde_json::from_slice(&fs::read(path).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?)
        .map_err(|_| "SLK_WEBBI_STORAGE_INVALID".into())
}

pub fn settings(root: &Path) -> Result<Value, String> {
    let path = root.join("settings.json");
    if path.exists() {
        return read(&path);
    }
    fs::create_dir_all(root).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    let seed =
        tempfile::NamedTempFile::new_in(root).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    let id = std::env::var("SLK_BI_DEVICE_ID")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or(format!(
            "BI-{}",
            &hash(&json!(format!(
                "{:?}-{:?}",
                seed.path(),
                std::time::SystemTime::now()
            )))?[..24]
        ));
    let value = json!({"url":"","device_id":id,"encrypted_token":null});
    let mut file =
        tempfile::NamedTempFile::new_in(root).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    file.write_all(&serde_json::to_vec(&value).map_err(|_| "SLK_WEBBI_JSON_INVALID")?)
        .map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    file.as_file()
        .sync_all()
        .map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?;
    match file.persist_noclobber(&path) {
        Ok(_) => Ok(value),
        Err(_) if path.exists() => read(&path),
        Err(_) => Err("SLK_WEBBI_STORAGE_UNAVAILABLE".into()),
    }
}

#[cfg(windows)]
pub fn protect(bytes: &[u8], encrypt: bool) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes
            .len()
            .try_into()
            .map_err(|_| "SLK_WEBBI_SECRET_INVALID")?,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let result = unsafe {
        if encrypt {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
    };
    if result == 0 {
        return Err("SLK_WEBBI_SECURE_STORE_UNAVAILABLE".into());
    }
    let value =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        LocalFree(output.pbData as *mut std::ffi::c_void);
    }
    Ok(value)
}
#[cfg(not(windows))]
pub fn protect(_: &[u8], _: bool) -> Result<Vec<u8>, String> {
    Err("SLK_WEBBI_SECURE_STORE_UNSUPPORTED".into())
}

pub fn token(settings: &Value) -> Result<Option<String>, String> {
    let Some(value) = settings.get("encrypted_token").filter(|v| !v.is_null()) else {
        return Ok(None);
    };
    let bytes: Vec<u8> =
        serde_json::from_value(value.clone()).map_err(|_| "SLK_WEBBI_SECURE_STORE_INVALID")?;
    String::from_utf8(protect(&bytes, false)?)
        .map(Some)
        .map_err(|_| "SLK_WEBBI_SECURE_STORE_INVALID".into())
}

pub fn pending_path(root: &Path, device: &str, run: &str) -> Result<std::path::PathBuf, String> {
    Ok(root
        .join("uploads")
        .join(format!("{}.json", hash(&json!([device, run]))?)))
}

pub fn matches_receipt(device: &str, run: &Value, receipt: &Value) -> Result<bool, String> {
    let Some(object) = receipt.as_object() else {
        return Ok(false);
    };
    let keys = [
        "device_id",
        "run_id",
        "payload_sha256",
        "archived",
        "source_id",
        "source_revision",
        "content_sha256",
        "saved_at",
    ];
    if keys.iter().any(|key| !object.contains_key(*key))
        || object
            .keys()
            .any(|key| !keys.contains(&key.as_str()) && key != "error")
    {
        return Ok(false);
    }
    let summary = &run["closeout_summary"];
    let status = &run["summary"];
    let archived = status["archived_at"]
        .as_str()
        .is_some_and(|s| !s.is_empty())
        || status["state"] == "archived"
        || (status["archive_control"] != "creator"
            && status["closure_state"]
                .as_str()
                .is_some_and(|s| s != "open"));
    Ok(receipt["error"].is_null()
        && receipt["device_id"] == device
        && receipt["run_id"] == run["run_id"]
        && receipt["payload_sha256"] == hash(run)?
        && receipt["source_id"] == summary["source_id"]
        && receipt["source_revision"] == summary["source_revision"]
        && receipt["content_sha256"] == summary["content_sha256"]
        && receipt["archived"] == archived
        && receipt["saved_at"].as_str().is_some_and(|s| !s.is_empty()))
}

pub fn receipt_error(receipt: &Value) -> String {
    match receipt["error"].as_str() {
        Some(
            code @ ("SLK_WEBBI_SUMMARY_REVISION_CONFLICT"
            | "SLK_WEBBI_SUMMARY_HASH_INVALID"
            | "SLK_WEBBI_STORE_BUSY"
            | "SLK_WEBBI_STORE_FAILED"),
        ) => code.to_owned(),
        _ => "SLK_WEBBI_RECEIPT_MISMATCH".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_payload_hash_matches_the_javascript_utf8_vector() {
        assert_eq!(
            hash(&json!({"z":1,"a":{"z":"原文\n","a":2}})).unwrap(),
            "17f14b035d448bb14d140e3cf6c12656652432591544f6f5e09b9ba44b638313"
        );
    }
    #[test]
    fn concurrent_initialization_keeps_one_stable_device_id() {
        let root = tempfile::tempdir().unwrap();
        let handles: Vec<_> = (0..8)
            .map(|_| {
                let path = root.path().to_path_buf();
                std::thread::spawn(move || settings(&path).unwrap()["device_id"].clone())
            })
            .collect();
        let ids: Vec<_> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect();
        assert!(ids.iter().all(|id| *id == ids[0]));
    }
    #[test]
    fn missing_config_has_persistent_id_and_atomic_pending_survives_restart() {
        let temp = tempfile::tempdir().unwrap();
        let first = settings(temp.path()).unwrap();
        assert_eq!(first, settings(temp.path()).unwrap());
        let path = pending_path(temp.path(), "A", "run").unwrap();
        atomic_write(&path, &json!({"run":{"run_id":"run"},"status":"pending"})).unwrap();
        assert_eq!(read(&path).unwrap()["status"], "pending");
        assert_ne!(path, pending_path(temp.path(), "B", "run").unwrap());
        let blocked = temp.path().join("file");
        fs::write(&blocked, "file").unwrap();
        assert!(atomic_write(&blocked.join("item"), &json!({})).is_err());
    }
    #[test]
    fn an_http_ack_or_previous_payload_is_not_a_saved_archive() {
        let run = json!({"run_id":"run","summary":{"archived_at":"2026-10-18T00:00:00Z"}});
        assert!(!matches_receipt("A", &run, &json!({"status":"accepted"})).unwrap());
        let receipt = json!({"device_id":"A","run_id":"run","payload_sha256":hash(&run).unwrap(),"archived":true,"source_id":null,"source_revision":null,"content_sha256":null,"saved_at":"now"});
        assert!(matches_receipt("A", &run, &receipt).unwrap());
        let mut polluted = receipt.clone();
        polluted["unexpected"] = json!("not persisted");
        assert!(!matches_receipt("A", &run, &polluted).unwrap());
        assert!(!matches_receipt("B", &run, &receipt).unwrap());
        assert!(!matches_receipt(
            "A",
            &json!({"run_id":"run","summary":{"archived_at":null}}),
            &receipt
        )
        .unwrap());
    }
    #[test]
    #[cfg(windows)]
    fn host_secure_store_roundtrip_does_not_contain_plaintext() {
        let plain = b"isolated-unit-test-token";
        let cipher = protect(plain, true).unwrap();
        assert!(!cipher.windows(plain.len()).any(|v| v == plain));
        assert_eq!(protect(&cipher, false).unwrap(), plain);
    }
}
