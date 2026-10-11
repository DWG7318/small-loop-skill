use std::process::Command;

use serde_json::Value;

#[test]
fn help_does_not_open_the_configured_database() {
    let result = Command::new(env!("CARGO_BIN_EXE_slk-bi-query"))
        .arg("--help")
        .env("SLK_CONFIG_PATH", "configuration-that-does-not-exist.json")
        .output()
        .expect("run standalone query help");
    assert!(result.status.success());
    let body: Value = serde_json::from_slice(&result.stdout).expect("JSON help response");
    assert_eq!(body["status"], "ok");
    assert!(body["help"].as_str().unwrap().contains("slk-bi-query"));
}

#[test]
fn missing_command_is_a_structured_usage_error() {
    let result = Command::new(env!("CARGO_BIN_EXE_slk-bi-query"))
        .env("SLK_CONFIG_PATH", "configuration-that-does-not-exist.json")
        .output()
        .expect("run standalone query without command");
    assert!(!result.status.success());
    let body: Value = serde_json::from_slice(&result.stderr).expect("JSON usage error");
    assert_eq!(body["code"], "SLK_QUERY_USAGE");
}
