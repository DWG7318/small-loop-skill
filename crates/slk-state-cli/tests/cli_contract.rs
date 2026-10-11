use std::process::Command;

use serde_json::Value;

#[test]
fn help_does_not_require_state_configuration_or_credentials() {
    let result = Command::new(env!("CARGO_BIN_EXE_slk-state"))
        .arg("--help")
        .env("SLK_CONFIG_PATH", "configuration-that-does-not-exist.json")
        .env_remove("SLK_ROLE_CREDENTIAL")
        .output()
        .expect("run standalone state command");
    assert!(result.status.success());
    let body: Value = serde_json::from_slice(&result.stdout).expect("JSON help response");
    assert_eq!(body["status"], "ok");
    assert!(body["help"]
        .as_str()
        .unwrap()
        .contains("commit-delivery-start"));
}

#[test]
fn version_is_the_product_version_not_the_extraction_tag() {
    let result = Command::new(env!("CARGO_BIN_EXE_slk-state"))
        .arg("--version")
        .output()
        .expect("run standalone state version");
    assert!(result.status.success());
    let body: Value = serde_json::from_slice(&result.stdout).expect("JSON version response");
    assert_eq!(body["version"], env!("CARGO_PKG_VERSION"));
}

#[test]
fn missing_command_is_a_structured_usage_error() {
    let result = Command::new(env!("CARGO_BIN_EXE_slk-state"))
        .output()
        .expect("run standalone state without command");
    assert!(!result.status.success());
    let body: Value = serde_json::from_slice(&result.stderr).expect("JSON usage error");
    assert_eq!(body["code"], "SLK_STATE_USAGE");
}
