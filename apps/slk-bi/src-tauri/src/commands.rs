use std::env;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{json, Value};
use slk_state_core::config::{default_config_path, resolve_data_root_at};
use slk_state_core::write::StateStore;

pub const REGISTERED_READ_COMMANDS: [&str; 9] = [
    "metadata", "projects", "runs", "run", "graph", "roles", "plans", "events", "evidence",
];

const BI_VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod sync_boundary_tests {
    use super::*;
    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    #[test]
    fn environment_url_override_cannot_reuse_another_destinations_secure_token() {
        let _guard = ENV_LOCK.lock().unwrap();
        let isolated = tempfile::tempdir().unwrap();
        let names = [
            "SLK_WEBBI_URL",
            "SLK_WEBBI_UPLOAD_TOKEN",
            "SLK_BI_DEVICE_ID",
        ];
        let original = names.map(|name| env::var_os(name));
        env::set_var(names[0], "https://different.example.invalid");
        env::remove_var(names[1]);
        env::set_var(names[2], "isolated-destination-test");
        crate::upload_state::atomic_write(&isolated.path().join("settings.json"), &json!({"url":"https://original.example.invalid","device_id":"isolated-destination-test","encrypted_token":[1,2,3]})).unwrap();
        let overridden = sync_settings_at(isolated.path()).unwrap();
        env::set_var(names[1], "fake-explicit-new-destination-token");
        let with_token = sync_settings_at(isolated.path()).unwrap();
        env::remove_var(names[1]);
        env::set_var(names[0], "https://original.example.invalid/");
        let same_destination = sync_settings_at(isolated.path()).unwrap();
        #[cfg(windows)]
        let replacement = {
            env::set_var(names[0], "https://different.example.invalid");
            let replacement = save_sync_settings_at(
                isolated.path(),
                json!({"url":"https://different.example.invalid","device_id":"isolated-destination-test","token":"fake-ui-token-for-B"}),
            );
            let stored = crate::upload_state::settings(isolated.path()).unwrap();
            env::remove_var(names[0]);
            let restored = sync_settings_at(isolated.path()).unwrap();
            (replacement, stored, restored)
        };
        for (name, value) in names.into_iter().zip(original) {
            if let Some(value) = value {
                env::set_var(name, value);
            } else {
                env::remove_var(name);
            }
        }
        assert_eq!(
            overridden["has_token"], false,
            "saved credentials are bound to their destination"
        );
        assert_eq!(overridden["sources"]["token"], "destination_mismatch");
        assert_eq!(with_token["has_token"], true);
        assert_eq!(same_destination["has_token"], true);
        #[cfg(windows)]
        {
            assert_eq!(replacement.0.unwrap()["has_token"], true);
            assert_eq!(replacement.1["url"], "https://original.example.invalid");
            assert_eq!(
                replacement.2["has_token"], false,
                "token for B must never become usable at A"
            );
        }
    }

    #[test]
    fn upload_url_requires_real_https_or_http_loopback_without_ambiguous_credentials() {
        let _guard = ENV_LOCK.lock().unwrap();
        let names = [
            "SLK_WEBBI_URL",
            "SLK_WEBBI_UPLOAD_TOKEN",
            "SLK_BI_DEVICE_ID",
        ];
        let original = names.map(|name| env::var_os(name));
        env::set_var(names[1], "test-token");
        env::set_var(names[2], "test-device");
        let cases = [
            ("http://localhost.evil.invalid", false),
            ("http://localhost@evil.invalid", false),
            ("https://user:password@example.com", false),
            ("https://example.com?next=http://evil.invalid", false),
            ("https://example.com/#fragment", false),
            ("http://localhost:8123", true),
            ("http://127.0.0.1:8123", true),
            ("http://[::1]:8123/base", true),
            ("https://example.com/webbi", true),
        ];
        let results: Vec<_> = cases
            .iter()
            .map(|(url, expected)| {
                env::set_var(names[0], url);
                (*url, sync_configuration().is_ok(), *expected)
            })
            .collect();
        for (name, value) in names.into_iter().zip(original) {
            if let Some(value) = value {
                env::set_var(name, value);
            } else {
                env::remove_var(name);
            }
        }
        for (url, actual, expected) in results {
            assert_eq!(actual, expected, "{url}");
        }
    }

    #[test]
    fn authenticated_upload_never_follows_a_redirect_to_another_path() {
        let _guard = ENV_LOCK.lock().unwrap();
        use std::io::{Read, Write};
        use std::net::TcpListener;
        use std::sync::{
            atomic::{AtomicBool, Ordering},
            Arc, Mutex,
        };
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let stop = Arc::new(AtomicBool::new(false));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let (done, captured) = (stop.clone(), requests.clone());
        let server = std::thread::spawn(move || {
            while !done.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream.set_nonblocking(false).unwrap();
                        stream
                            .set_read_timeout(Some(Duration::from_secs(2)))
                            .unwrap();
                        let mut bytes = [0; 8192];
                        let size = stream.read(&mut bytes).unwrap();
                        let mut rows = captured.lock().unwrap();
                        rows.push(String::from_utf8_lossy(&bytes[..size]).into_owned());
                        let reply = if rows.len() == 1 {
                            format!("HTTP/1.1 302 Found\r\nLocation: http://localhost:{}/credential-sink\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", address.port())
                        } else {
                            "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                                .into()
                        };
                        stream.write_all(reply.as_bytes()).unwrap();
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(error) => panic!("{error}"),
                }
            }
        });
        let names = [
            "SLK_WEBBI_URL",
            "SLK_WEBBI_UPLOAD_TOKEN",
            "SLK_BI_DEVICE_ID",
        ];
        let original = names.map(|name| env::var_os(name));
        env::set_var(names[0], format!("http://localhost:{}", address.port()));
        env::set_var(names[1], "private-upload-token");
        env::set_var(names[2], "test-device");
        let payload = json!({
            "schema_version":"slk.bi.upload/v1", "bi_version":BI_VERSION, "upload_id":"upload-test",
            "generated_at":"2026-10-10T00:00:00Z", "device":{"device_id":"test-device", "device_name":"Test"}, "runs":[]
        });
        let (endpoint, token, _) = sync_configuration().unwrap().unwrap();
        let result = tauri::async_runtime::block_on(post_upload(&endpoint, &token, &payload));
        stop.store(true, Ordering::SeqCst);
        server.join().unwrap();
        for (name, value) in names.into_iter().zip(original) {
            if let Some(value) = value {
                env::set_var(name, value);
            } else {
                env::remove_var(name);
            }
        }
        assert_eq!(result.unwrap_err(), "SLK_WEBBI_UPLOAD_REJECTED:302");
        assert_eq!(requests.lock().unwrap().len(), 1);
    }

    #[test]
    fn upload_resumes_after_failure_ignores_old_ack_and_deduplicates_saved_runs() {
        use std::io::{Read, Write};
        use std::net::TcpListener;
        use std::sync::{
            atomic::{AtomicUsize, Ordering},
            Arc,
        };
        let _guard = ENV_LOCK.lock().unwrap();
        let isolated = tempfile::tempdir().unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let seen = Arc::new(AtomicUsize::new(0));
        let seen_server = seen.clone();
        let server = std::thread::spawn(move || {
            for _ in 0..3 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut bytes = Vec::new();
                let mut part = [0u8; 8192];
                let (header_end, length) = loop {
                    let size = stream.read(&mut part).unwrap();
                    assert!(size > 0);
                    bytes.extend_from_slice(&part[..size]);
                    if let Some(index) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                        let header = String::from_utf8_lossy(&bytes[..index]);
                        let length: usize = header
                            .lines()
                            .find_map(|line| {
                                line.to_ascii_lowercase()
                                    .strip_prefix("content-length:")
                                    .map(|v| v.trim().parse().unwrap())
                            })
                            .unwrap();
                        break (index + 4, length);
                    }
                };
                while bytes.len() < header_end + length {
                    let size = stream.read(&mut part).unwrap();
                    assert!(size > 0);
                    bytes.extend_from_slice(&part[..size]);
                }
                let payload: Value =
                    serde_json::from_slice(&bytes[header_end..header_end + length]).unwrap();
                let index = seen_server.fetch_add(1, Ordering::SeqCst);
                let response = if index == 0 {
                    json!({"status":"accepted"})
                } else {
                    let run = &payload["runs"][0]["run"];
                    json!({"receipts":[{"device_id":"isolated-device","run_id":run["run_id"],"payload_sha256":crate::upload_state::hash(run).unwrap(),"archived":false,"source_id":null,"source_revision":null,"content_sha256":null,"saved_at":"2026-10-18T00:00:00Z"}]})
                };
                let body = response.to_string();
                write!(stream, "HTTP/1.1 202 Accepted\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).unwrap();
            }
        });
        let names = [
            "SLK_WEBBI_URL",
            "SLK_WEBBI_UPLOAD_TOKEN",
            "SLK_BI_DEVICE_ID",
        ];
        let original = names.map(|key| env::var_os(key));
        env::set_var(names[0], format!("http://localhost:{}", address.port()));
        env::set_var(names[1], "fake-isolated-token");
        env::set_var(names[2], "isolated-device");
        let envelope = json!({"schema_version":"slk.bi.upload/v1","bi_version":BI_VERSION,"upload_id":"u1","generated_at":"2026-10-18T00:00:00Z","device":{"device_id":"isolated-device","device_name":"未获取"},"runs":[{"run":{"run_id":"good"},"messages":[]}]});
        let first =
            tauri::async_runtime::block_on(sync_webbi_at(isolated.path(), envelope.clone()))
                .unwrap();
        assert_eq!(first["status"], "failed");
        assert_eq!(first["runs"][0]["error"], "SLK_WEBBI_RECEIPT_MISSING");
        // Reopening reads the prior pending payload even if the source is temporarily absent.
        let mut restart = envelope.clone();
        restart["runs"] = json!([]);
        let saved =
            tauri::async_runtime::block_on(sync_webbi_at(isolated.path(), restart)).unwrap();
        assert_eq!(saved["status"], "uploaded");
        let repeated =
            tauri::async_runtime::block_on(sync_webbi_at(isolated.path(), envelope.clone()))
                .unwrap();
        assert_eq!(repeated["status"], "uploaded");
        assert_eq!(seen.load(Ordering::SeqCst), 2);
        let corrupt =
            crate::upload_state::pending_path(isolated.path(), "isolated-device", "a-corrupt")
                .unwrap();
        std::fs::write(&corrupt, b"{invalid pending JSON").unwrap();
        let mut mixed = envelope.clone();
        mixed["runs"] = json!([
            {"run":{"run_id":"a-corrupt"},"messages":[]},
            {"run":{"run_id":"oversize","body":"x".repeat(10*1024*1024)},"messages":[]},
            {"run":{"run_id":"good-2"},"messages":[]}, {"broken":true}
        ]);
        let mixed = tauri::async_runtime::block_on(sync_webbi_at(isolated.path(), mixed));
        assert!(
            mixed.is_ok(),
            "one corrupt pending file must not abort healthy Runs: {mixed:?}"
        );
        let mixed = mixed.unwrap();
        assert_eq!(mixed["status"], "failed");
        assert_eq!(std::fs::read(&corrupt).unwrap(), b"{invalid pending JSON");
        assert!(mixed["runs"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r["run_id"] == "a-corrupt" && r["status"] == "failed"));
        assert!(mixed["runs"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r["run_id"] == "good-2" && r["status"] == "uploaded"));
        server.join().unwrap();
        assert_eq!(seen.load(Ordering::SeqCst), 3);
        // Real refused loopback connection: error remains pending and resumes on next launch.
        env::set_var(names[0], "http://127.0.0.1:1");
        let failed =
            tauri::async_runtime::block_on(sync_webbi_at(isolated.path(), envelope)).unwrap();
        assert_eq!(failed["status"], "failed");
        for (key, value) in names.into_iter().zip(original) {
            if let Some(value) = value {
                env::set_var(key, value);
            } else {
                env::remove_var(key);
            }
        }
    }
}

fn nonempty_env(name: &str) -> Option<String> {
    env::var(name).ok().filter(|value| !value.trim().is_empty())
}

fn fallback_device_name() -> String {
    "未获取".into()
}

fn private_root() -> Result<PathBuf, String> {
    Ok(default_path()?.with_file_name("bi-private"))
}

pub fn sync_settings_at(root: &Path) -> Result<Value, String> {
    let saved = crate::upload_state::settings(root)?;
    let env_url = nonempty_env("SLK_WEBBI_URL");
    let env_id = nonempty_env("SLK_BI_DEVICE_ID");
    let env_token = nonempty_env("SLK_WEBBI_UPLOAD_TOKEN");
    let url = env_url
        .as_deref()
        .unwrap_or(saved["url"].as_str().unwrap_or(""));
    let destination_matches = stored_token_destination_matches(&saved, url);
    Ok(json!({"url":url,
        "device_id":env_id.as_deref().unwrap_or(saved["device_id"].as_str().unwrap_or("")),
        "has_token":env_token.is_some() || (destination_matches && !saved["encrypted_token"].is_null()),
        "sources":{"url":if env_url.is_some(){"environment"}else{"saved"},"device_id":if env_id.is_some(){"environment"}else{"saved"},"token":if env_token.is_some(){"environment"}else if !destination_matches && !saved["encrypted_token"].is_null(){"destination_mismatch"}else{"secure_store"}}}))
}

fn stored_token_destination_matches(saved: &Value, url: &str) -> bool {
    match (
        upload_endpoint(
            saved["token_url"]
                .as_str()
                .unwrap_or(saved["url"].as_str().unwrap_or("")),
        ),
        upload_endpoint(url),
    ) {
        (Ok(saved_endpoint), Ok(effective_endpoint)) => saved_endpoint == effective_endpoint,
        _ => false,
    }
}

#[tauri::command]
pub fn webbi_settings() -> Result<Value, String> {
    sync_settings_at(&private_root()?)
}

pub fn save_sync_settings_at(root: &Path, input: Value) -> Result<Value, String> {
    let mut saved = crate::upload_state::settings(root)?;
    let object = input.as_object().ok_or("SLK_WEBBI_SETTINGS_INVALID")?;
    if object
        .keys()
        .any(|key| !["url", "device_id", "token"].contains(&key.as_str()))
    {
        return Err("SLK_WEBBI_SETTINGS_INVALID".into());
    }
    let url = if nonempty_env("SLK_WEBBI_URL").is_some() {
        saved["url"].as_str().unwrap_or("")
    } else {
        input["url"]
            .as_str()
            .ok_or("SLK_WEBBI_SETTINGS_INVALID")?
            .trim()
    }
    .to_owned();
    if !url.is_empty() {
        upload_endpoint(&url)?;
    }
    let id = if nonempty_env("SLK_BI_DEVICE_ID").is_some() {
        saved["device_id"].as_str()
    } else {
        input["device_id"].as_str()
    }
    .filter(|s| !s.trim().is_empty() && s.len() <= 128)
    .ok_or("SLK_WEBBI_DEVICE_INVALID")?
    .to_owned();
    let token = input["token"]
        .as_str()
        .filter(|s| !s.trim().is_empty() && nonempty_env("SLK_WEBBI_UPLOAD_TOKEN").is_none());
    if !url.is_empty()
        && url != saved["url"].as_str().unwrap_or("")
        && !saved["encrypted_token"].is_null()
        && token.is_none()
    {
        return Err("SLK_WEBBI_NEW_DESTINATION_TOKEN_REQUIRED".into());
    }
    if let Some(token) = token {
        let token_url = nonempty_env("SLK_WEBBI_URL").unwrap_or_else(|| url.clone());
        upload_endpoint(&token_url)?;
        saved["encrypted_token"] = json!(crate::upload_state::protect(token.as_bytes(), true)?);
        saved["token_url"] = json!(token_url);
    }
    if url.is_empty() && nonempty_env("SLK_WEBBI_URL").is_none() {
        saved["encrypted_token"] = Value::Null;
        saved["token_url"] = Value::Null;
    }
    saved["url"] = json!(url);
    saved["device_id"] = json!(id);
    crate::upload_state::atomic_write(&root.join("settings.json"), &saved)?;
    sync_settings_at(root)
}

#[tauri::command]
pub fn save_webbi_settings(input: Value) -> Result<Value, String> {
    save_sync_settings_at(&private_root()?, input)
}

#[tauri::command]
pub fn metadata() -> Result<Value, String> {
    metadata_at(&private_root()?)
}

pub fn metadata_at(root: &Path) -> Result<Value, String> {
    let device_name = nonempty_env("SLK_BI_DEVICE_NAME").unwrap_or_else(fallback_device_name);
    let settings = sync_settings_at(root)?;
    Ok(json!({
        "schema_version": "slk.bi.metadata/v1",
        "bi_version": BI_VERSION,
        "device_id": settings["device_id"],
        "device_name": device_name,
        "webbi_sync_enabled": settings["url"].as_str().is_some_and(|s| !s.is_empty()) && settings["has_token"] == true
    }))
}

pub fn validate_sync_payload(payload: &Value, expected_device_id: &str) -> Result<(), String> {
    let object = payload
        .as_object()
        .ok_or_else(|| "SLK_WEBBI_UPLOAD_INVALID".to_string())?;
    let expected = [
        "schema_version",
        "bi_version",
        "upload_id",
        "generated_at",
        "device",
        "runs",
    ];
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err("SLK_WEBBI_UPLOAD_INVALID".into());
    }
    if object.get("schema_version").and_then(Value::as_str) != Some("slk.bi.upload/v1")
        || !matches!(
            object.get("bi_version").and_then(Value::as_str),
            Some("1.1.0")
                | Some("1.1.1")
                | Some("1.1.2")
                | Some("1.1.3")
                | Some("1.1.4")
                | Some("1.1.5")
                | Some(BI_VERSION)
        )
    {
        return Err("SLK_WEBBI_UPLOAD_VERSION_UNSUPPORTED".into());
    }
    let device = object
        .get("device")
        .and_then(Value::as_object)
        .ok_or_else(|| "SLK_WEBBI_DEVICE_INVALID".to_string())?;
    if device.len() != 2
        || device.get("device_id").and_then(Value::as_str) != Some(expected_device_id)
        || device
            .get("device_name")
            .and_then(Value::as_str)
            .is_none_or(|name| name.trim().is_empty())
    {
        return Err("SLK_WEBBI_DEVICE_INVALID".into());
    }
    if object
        .get("upload_id")
        .and_then(Value::as_str)
        .is_none_or(|value| value.trim().is_empty())
        || !object.get("runs").is_some_and(Value::is_array)
    {
        return Err("SLK_WEBBI_UPLOAD_INVALID".into());
    }
    if serde_json::to_vec(payload)
        .map_err(|error| error.to_string())?
        .len()
        > 10 * 1024 * 1024
    {
        return Err("SLK_WEBBI_UPLOAD_TOO_LARGE".into());
    }
    Ok(())
}

#[cfg(test)]
fn sync_configuration() -> Result<Option<(String, String, String)>, String> {
    let Some(url) = nonempty_env("SLK_WEBBI_URL") else {
        return Ok(None);
    };
    let Some(token) = nonempty_env("SLK_WEBBI_UPLOAD_TOKEN") else {
        return Ok(None);
    };
    let Some(device_id) = nonempty_env("SLK_BI_DEVICE_ID") else {
        return Ok(None);
    };
    Ok(Some((upload_endpoint(&url)?, token, device_id)))
}

fn upload_endpoint(url: &str) -> Result<String, String> {
    let mut endpoint =
        reqwest::Url::parse(&url).map_err(|_| "SLK_WEBBI_URL_INVALID".to_string())?;
    let loopback = endpoint.host_str().is_some_and(|host| {
        host.eq_ignore_ascii_case("localhost")
            || host
                .trim_matches(['[', ']'])
                .parse::<std::net::IpAddr>()
                .is_ok_and(|ip| ip.is_loopback())
    });
    if !(endpoint.scheme() == "https" || (endpoint.scheme() == "http" && loopback))
        || endpoint.host_str().is_none()
        || !endpoint.username().is_empty()
        || endpoint.password().is_some()
        || endpoint.query().is_some()
        || endpoint.fragment().is_some()
    {
        return Err("SLK_WEBBI_URL_INVALID".into());
    }
    endpoint.set_path(&format!(
        "{}/api/v1/uploads",
        endpoint.path().trim_end_matches('/')
    ));
    Ok(endpoint.to_string())
}

#[tauri::command]
pub async fn sync_webbi(payload: Value) -> Result<Value, String> {
    sync_webbi_at(&private_root()?, payload).await
}

pub async fn sync_webbi_at(root: &Path, payload: Value) -> Result<Value, String> {
    use crate::upload_state::{atomic_write, hash, matches_receipt, pending_path, read};
    let settings = sync_settings_at(root)?;
    let device_id = settings["device_id"]
        .as_str()
        .ok_or("SLK_WEBBI_DEVICE_INVALID")?
        .to_owned();
    let configured =
        settings["url"].as_str().is_some_and(|s| !s.is_empty()) && settings["has_token"] == true;
    // Validate each Run independently below so one oversize item cannot block its peers.
    let mut header = payload.clone();
    header["runs"] = json!([]);
    validate_sync_payload(&header, &device_id)?;
    let rows = payload["runs"]
        .as_array()
        .ok_or("SLK_WEBBI_UPLOAD_INVALID")?;
    let mut results = vec![];
    let mut pending = std::collections::BTreeMap::new();
    for item in rows {
        let Some(run_id) = item["run"]["run_id"].as_str().filter(|s| !s.is_empty()) else {
            results
                .push(json!({"run_id":"未识别","status":"failed","error":"SLK_WEBBI_RUN_INVALID"}));
            continue;
        };
        pending.insert(run_id.to_owned(), item.clone());
    }
    let folder = root.join("uploads");
    if folder.exists() {
        for entry in std::fs::read_dir(&folder).map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")? {
            let path = entry.map_err(|_| "SLK_WEBBI_STORAGE_UNAVAILABLE")?.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let saved = match read(&path) {
                Ok(value) => value,
                Err(error) => {
                    results.push(json!({"run_id":"待上传记录","status":"failed","error":error}));
                    continue;
                }
            };
            if saved["device_id"] == device_id && saved["status"] != "uploaded" {
                if let Some(id) = saved["item"]["run"]["run_id"].as_str() {
                    pending
                        .entry(id.to_owned())
                        .or_insert(saved["item"].clone());
                }
            }
        }
    }
    let endpoint = if configured {
        Some(upload_endpoint(settings["url"].as_str().unwrap())?)
    } else {
        None
    };
    let token = if configured {
        if let Some(token) = nonempty_env("SLK_WEBBI_UPLOAD_TOKEN") {
            Some(token)
        } else {
            let saved = crate::upload_state::settings(root)?;
            if !stored_token_destination_matches(&saved, settings["url"].as_str().unwrap_or("")) {
                return Err("SLK_WEBBI_NEW_DESTINATION_TOKEN_REQUIRED".into());
            }
            crate::upload_state::token(&saved)?
        }
    } else {
        None
    };
    for (run_id, item) in pending {
        let identity = format!("{}:{}", root.display(), hash(&json!([device_id, run_id]))?);
        let Some(_guard) = UploadGuard::acquire(identity) else {
            results.push(json!({"run_id":run_id,"status":"pending"}));
            continue;
        };
        let path = pending_path(root, &device_id, &run_id)?;
        let fingerprint = hash(&item)?;
        let previous = if path.exists() {
            match read(&path) {
                Ok(saved) => Some(saved),
                Err(error) => {
                    // Preserve the unreadable record for recovery; isolate its failure to this Run.
                    results.push(json!({"run_id":run_id,"status":"failed","error":error}));
                    continue;
                }
            }
        } else {
            None
        };
        if let Some(previous) = &previous {
            if previous["fingerprint"] == fingerprint
                && previous["status"] == "uploaded"
                && previous["destination"] == settings["url"]
            {
                results.push(
                    json!({"run_id":run_id,"status":"uploaded","receipt":previous["receipt"]}),
                );
                continue;
            }
        }
        let mut envelope = header.clone();
        envelope["runs"] = json!([item]);
        let mut state = json!({"device_id":device_id,"item":item,"fingerprint":fingerprint,"status":"pending","destination":settings["url"],"envelope":envelope});
        if let Some(previous) = &previous {
            if previous["fingerprint"] == fingerprint && previous["destination"] == settings["url"]
            {
                state["envelope"] = previous["envelope"].clone();
            }
        }
        let attempt = async {
            atomic_write(&path, &state)?;
            validate_sync_payload(&state["envelope"], &device_id)?;
            let (Some(endpoint), Some(token)) = (&endpoint, &token) else {
                return Ok::<_, String>(None);
            };
            let response = post_upload(endpoint, token, &state["envelope"]).await?;
            let receipt = response["receipts"]
                .as_array()
                .and_then(|receipts| {
                    receipts.iter().find(|receipt| {
                        receipt["run_id"] == run_id && receipt["device_id"] == device_id
                    })
                })
                .ok_or("SLK_WEBBI_RECEIPT_MISSING")?;
            if !matches_receipt(&device_id, &item["run"], receipt)? {
                return Err(crate::upload_state::receipt_error(receipt));
            }
            Ok(Some(receipt.clone()))
        }
        .await;
        match attempt {
            Ok(Some(receipt)) => {
                state = json!({"device_id":device_id,"run_id":run_id,"fingerprint":fingerprint,"status":"uploaded","receipt":receipt,"destination":settings["url"]});
            }
            Ok(None) => {
                state["status"] = json!("disabled");
            }
            Err(error) => {
                state["status"] = json!("failed");
                state["error"] = json!(error);
            }
        }
        if let Err(error) = atomic_write(&path, &state) {
            state["status"] = json!("failed");
            state["error"] = json!(error);
        }
        results.push(json!({"run_id":run_id,"status":state["status"],"error":state["error"],"receipt":state["receipt"]}));
    }
    let status = if !configured {
        "disabled"
    } else if results.iter().any(|r| r["status"] == "failed") {
        "failed"
    } else if results.iter().any(|r| r["status"] == "pending") {
        "pending"
    } else {
        "uploaded"
    };
    Ok(json!({"status":status,"upload_id":payload["upload_id"],"runs":results}))
}

static UPLOADING: std::sync::Mutex<Option<std::collections::HashSet<String>>> =
    std::sync::Mutex::new(None);
struct UploadGuard(String);
impl UploadGuard {
    fn acquire(key: String) -> Option<Self> {
        let mut guard = UPLOADING.lock().ok()?;
        if guard
            .get_or_insert_with(Default::default)
            .insert(key.clone())
        {
            Some(Self(key))
        } else {
            None
        }
    }
}
impl Drop for UploadGuard {
    fn drop(&mut self) {
        if let Ok(mut guard) = UPLOADING.lock() {
            if let Some(keys) = guard.as_mut() {
                keys.remove(&self.0);
            }
        }
    }
}

async fn post_upload(endpoint: &str, token: &str, payload: &Value) -> Result<Value, String> {
    let upload_id = payload
        .get("upload_id")
        .and_then(Value::as_str)
        .expect("validated upload id")
        .to_string();
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "SLK_WEBBI_CLIENT_UNAVAILABLE".to_string())?
        .post(endpoint)
        .bearer_auth(token)
        .header("x-slk-upload-id", &upload_id)
        .json(&payload)
        .send()
        .await
        .map_err(|_| "SLK_WEBBI_UPLOAD_FAILED".to_string())?;
    if !response.status().is_success() {
        return Err(format!(
            "SLK_WEBBI_UPLOAD_REJECTED:{}",
            response.status().as_u16()
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "SLK_WEBBI_RECEIPT_INVALID".into())
}

fn store_from(config_path: &Path) -> Result<StateStore, String> {
    let root = resolve_data_root_at(config_path).map_err(|error| error.to_string())?;
    Ok(StateStore::new(root))
}

pub fn default_path() -> Result<PathBuf, String> {
    default_config_path().map_err(|error| error.to_string())
}

pub fn projects_from(config_path: &Path) -> Result<Value, String> {
    combined(config_path, "projects")
}

pub fn runs_from(config_path: &Path, project_id: Option<String>) -> Result<Value, String> {
    let mut result = combined(config_path, "runs")?;
    if let Some(project) = project_id {
        result["runs"]
            .as_array_mut()
            .unwrap()
            .retain(|r| r["project_id"] == project);
    }
    Ok(result)
}

fn combined(config_path: &Path, kind: &str) -> Result<Value, String> {
    let local = crate::sources::collect(&config_path.with_file_name("bi-sources"));
    let mut warnings = local.warnings;
    let stored = store_from(config_path).and_then(|store| {
        if kind == "projects" {
            store.projects_view()
        } else {
            store.runs_view(None)
        }
        .map_err(|e| e.to_string())
    });
    let mut result = match stored {
        Ok(value) => value,
        Err(error) => {
            if local.runs.is_empty() && config_path.exists() {
                return Err(error);
            }
            if config_path.exists() {
                warnings.push(format!("State database: {error}"));
            }
            json!({"schema_version":format!("slk.bi.{kind}/v1"),kind:[]})
        }
    };
    let incoming = if kind == "projects" {
        local.projects
    } else {
        local
            .runs
            .into_iter()
            .map(|r| r["summary"].clone())
            .collect()
    };
    let rows = result[kind]
        .as_array_mut()
        .ok_or("SLK_BI_PROJECTION_INVALID")?;
    let id_key = if kind == "projects" {
        "project_id"
    } else {
        "run_id"
    };
    for row in incoming {
        if let Some(previous) = rows.iter_mut().find(|r| r[id_key] == row[id_key]) {
            if kind == "projects" {
                previous["run_count"] = json!(
                    previous["run_count"].as_u64().unwrap_or(0)
                        + row["run_count"].as_u64().unwrap_or(0)
                );
            } else {
                warnings.push(format!("Run identity collision: {}", row[id_key]));
            }
        } else {
            rows.push(row);
        }
    }
    if !warnings.is_empty() {
        result["source_warnings"] = json!(warnings);
    }
    Ok(result)
}

pub fn run_from(config_path: &Path, run_id: &str, view: &str) -> Result<Value, String> {
    if let Some(run) = crate::sources::load_run(&config_path.with_file_name("bi-sources"), run_id)?
    {
        if store_from(config_path)
            .and_then(|s| s.run_view(run_id).map_err(|e| e.to_string()))
            .is_ok()
        {
            return Err("SLK_BI_SOURCE_IDENTITY_COLLISION".into());
        }
        if view == "run" {
            return Ok(run);
        }
        let key = match view {
            "graph" => "go_nodes",
            "plans" => "plan_revisions",
            key => key,
        };
        return Ok(
            json!({"schema_version":format!("slk.bi.{view}/v1"),"run_id":run_id,key:run[key]}),
        );
    }
    let store = store_from(config_path)?;
    let result = match view {
        "run" => store.run_view(run_id),
        "graph" => store.graph_view(run_id),
        "roles" => store.roles_view(run_id),
        "plans" => store.plans_view(run_id),
        "events" => store.events_view(run_id),
        "evidence" => store.evidence_view(run_id),
        _ => unreachable!("registered read view"),
    };
    result.map_err(|error| error.to_string())
}

#[tauri::command]
pub fn projects() -> Result<Value, String> {
    projects_from(&default_path()?)
}

#[tauri::command]
pub fn runs(project_id: Option<String>) -> Result<Value, String> {
    runs_from(&default_path()?, project_id)
}

#[tauri::command]
pub fn run(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "run")
}

#[tauri::command]
pub fn graph(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "graph")
}

#[tauri::command]
pub fn roles(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "roles")
}

#[tauri::command]
pub fn plans(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "plans")
}

#[tauri::command]
pub fn events(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "events")
}

#[tauri::command]
pub fn evidence(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "evidence")
}
