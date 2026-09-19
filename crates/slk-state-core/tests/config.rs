use std::path::Path;

use slk_state_core::config::{
    configure_at, parse_config, resolve_data_root_at, validate_data_root,
};

#[test]
fn configure_round_trips_one_absolute_data_root() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let config = temp.path().join("local-app-data/SLK/config.json");
    let data = temp.path().join("state");
    std::fs::create_dir_all(&data).expect("data root");

    configure_at(&config, &data).expect("configure root");

    assert_eq!(
        resolve_data_root_at(&config).expect("resolve root"),
        data.canonicalize().expect("canonical data root")
    );
}

#[test]
fn relative_or_two_authoritative_roots_are_rejected() {
    assert!(validate_data_root(Path::new("relative")).is_err());
    assert!(parse_config(
        r#"{"schema_version":"slk.config/v1","data_root":"A","secondary_root":"B"}"#
    )
    .is_err());
}

#[test]
fn replacing_configuration_switches_one_authority_atomically() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let config = temp.path().join("config.json");
    let first = temp.path().join("first");
    let second = temp.path().join("second");
    std::fs::create_dir_all(&first).expect("first root");
    std::fs::create_dir_all(&second).expect("second root");

    configure_at(&config, &first).expect("first configure");
    configure_at(&config, &second).expect("second configure");

    assert_eq!(
        resolve_data_root_at(&config).expect("resolve switched root"),
        second.canonicalize().expect("canonical second root")
    );
    assert!(!config.with_extension("json.tmp").exists());
}
