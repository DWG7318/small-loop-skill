use slk_bi_desktop_lib::sources::{archive, collect, project_markdown, register};
use std::fs;

const RECORD: &str = "# SLK Run — R1\n\n## Run 定义\n- 创建Supervisor：supervisor-a\n- 目标：小工程\n- SLK版本：项目 3.0.9\n- 开始时间：2026-10-14T00:00:00Z\n\n## 当前摘要（唯一，按事实更新）\n- 当前状态：CLOSED / D2 PASS\n- 最终CELL与进度：1、2 D1 PASS / 2/2\n\n## 成员\n| 角色 | 对话/任务ID | 状态 |\n|---|---|---|\n| Supervisor | supervisor-a | 保留 |\n| Checker | checker-a | ARCHIVED |\n| Worker | worker-a | ARCHIVED |\n\n## GO 与 CELL 计划\n- 1：读取配置\n- 2：保存配置\n\n## CELL 历史\n历史 D1 FAIL 不应覆盖当前摘要\n";

fn with_summary(body: &str) -> String {
    format!("{RECORD}\n## 结项总结\n- 记录者：supervisor-a\n- 记录时间：2026-10-18T00:00:00Z\n\n{body}\n")
}

#[test]
fn formal_summary_preserves_body_signature_and_rejects_conflicting_sections_and_authors() {
    assert!(project_markdown(RECORD, "p", "P")
        .unwrap()
        .get("closeout_summary")
        .is_none());
    let input = with_summary("恢复原交接后完成，未重跑验收。\n\n第二段");
    let run = project_markdown(
        &input.replace(
            "- 目标：",
            "- 电脑名：PC-A\n- IP地址：\n- OS版本：Windows 11\n- 目标：",
        ),
        "p",
        "P",
    )
    .unwrap();
    assert_eq!(
        run["closeout_summary"]["body"],
        "恢复原交接后完成，未重跑验收。\n\n第二段\n"
    );
    assert_eq!(run["device_signature"]["computer_name"], "PC-A");
    assert!(run["device_signature"]["ip_address"].is_null());
    assert!(project_markdown(
        &input.replace("记录者：supervisor-a", "记录者：worker-a"),
        "p",
        "P"
    )
    .is_err());
    assert!(project_markdown(&format!("{input}\n## 结项总结\n不同正文"), "p", "P").is_err());
    assert!(project_markdown(&format!("{input}\n## 结项总结"), "p", "P").is_err());
    assert!(project_markdown(
        &input.replace(
            "记录者：supervisor-a",
            "记录者：supervisor-a\n- 记录者：worker-a"
        ),
        "p",
        "P"
    )
    .is_err());
    assert!(
        project_markdown(&input.replace("## 结项总结", "## 结项总结草稿"), "p", "P")
            .unwrap()
            .get("closeout_summary")
            .is_none()
    );
}

#[test]
fn summary_revision_survives_restarts_and_archive_correction_does_not_rewrite_snapshot() {
    use slk_bi_desktop_lib::sources::{load_run, record_summary};
    let temp = tempfile::tempdir().unwrap();
    let record = temp.path().join("run.md");
    let registry = temp.path().join("sources");
    fs::write(&record, with_summary("原文")).unwrap();
    register(&registry, &record, "p", "P", "supervisor-a").unwrap();
    let first = load_run(&registry, "R1").unwrap().unwrap();
    assert_eq!(first["closeout_summary"]["source_revision"], 1);
    assert_eq!(
        load_run(&registry, "R1").unwrap().unwrap()["closeout_summary"],
        first["closeout_summary"]
    );
    let archived = archive(&registry, "R1", "supervisor-a").unwrap();
    let snapshot_path = fs::read_dir(&registry)
        .unwrap()
        .map(|x| x.unwrap().path())
        .find(|p| p.extension().is_some_and(|x| x == "archive"))
        .unwrap();
    let snapshot = fs::read(&snapshot_path).unwrap();
    fs::write(&record, with_summary("更正：原事实不动")).unwrap();
    assert!(record_summary(&registry, "R1", "worker-a").is_err());
    record_summary(&registry, "R1", "supervisor-a").unwrap();
    let changed = load_run(&registry, "R1").unwrap().unwrap();
    assert_eq!(changed["closeout_summary"]["source_revision"], 2);
    assert_eq!(changed["summary"], archived["summary"]);
    assert_eq!(
        changed["administrative_snapshot"],
        archived["administrative_snapshot"]
    );
    assert_eq!(fs::read(snapshot_path).unwrap(), snapshot);
    assert_eq!(archive(&registry, "R1", "supervisor-a").unwrap(), archived);
}

#[test]
fn reads_legacy_markdown_without_inventing_ow_messages_models_or_timings() {
    let run = project_markdown(RECORD, "project-a", "Project A").unwrap();
    assert_eq!(run["summary"]["slk_version"], "3.0.9");
    assert_eq!(
        run["source_record"]["creator_supervisor_id"],
        "supervisor-a"
    );
    assert_eq!(run["summary"]["closure_state"], "closed");
    assert_eq!(run["roles"].as_array().unwrap().len(), 3);
    assert_eq!(
        run["go_nodes"][0]["cell_nodes"].as_array().unwrap().len(),
        2
    );
    assert_eq!(run["events"], serde_json::json!([]));
    assert_eq!(run["roles"][0]["model"], "未提供");
}

#[test]
fn only_creator_can_register_and_archive_and_source_is_never_written() {
    let temp = tempfile::tempdir().unwrap();
    let record = temp.path().join("run.md");
    fs::write(&record, RECORD).unwrap();
    let registry = temp.path().join("sources");
    assert!(register(&registry, &record, "p", "Project", "supervisor-b").is_err());
    register(&registry, &record, "p", "Project", "supervisor-a").unwrap();
    for other in ["supervisor-b", "checker-a", "worker-a", "", "overwatcher-a"] {
        assert!(archive(&registry, "R1", other).is_err());
    }
    archive(&registry, "R1", "supervisor-a").unwrap();
    archive(&registry, "R1", "supervisor-a").unwrap();
    assert_eq!(fs::read_to_string(&record).unwrap(), RECORD);
    fs::remove_file(&record).unwrap();
    let result = collect(&registry);
    assert_eq!(result.runs.len(), 1);
    assert!(result.runs[0]["summary"]["archived_at"].is_string());
    assert_eq!(
        result.runs[0]["source_record"]["creator_supervisor_id"],
        "supervisor-a"
    );
}

#[test]
fn never_archives_active_run_or_allows_silent_creator_replacement() {
    let temp = tempfile::tempdir().unwrap();
    let record = temp.path().join("run.md");
    fs::write(&record, RECORD.replace("CLOSED / D2 PASS", "Worker 工作中")).unwrap();
    let registry = temp.path().join("sources");
    register(&registry, &record, "p", "Project", "supervisor-a").unwrap();
    assert!(archive(&registry, "R1", "supervisor-a")
        .unwrap_err()
        .contains("NOT_CLOSED"));
    fs::write(&record, RECORD.replace("supervisor-a", "supervisor-b")).unwrap();
    assert!(register(&registry, &record, "p", "Project", "supervisor-b").is_err());
    assert!(archive(&registry, "R1", "supervisor-b").is_err());
}

#[test]
fn malformed_source_does_not_remove_other_runs_or_modify_unknown_format() {
    let temp = tempfile::tempdir().unwrap();
    let registry = temp.path().join("sources");
    for id in ["R1", "R2"] {
        let record = temp.path().join(format!("{id}.md"));
        fs::write(&record, RECORD.replace("R1", id)).unwrap();
        register(&registry, &record, "p", "Project", "supervisor-a").unwrap();
    }
    fs::write(temp.path().join("R2.md"), "unrecognized").unwrap();
    let result = collect(&registry);
    assert_eq!(result.runs.len(), 1);
    assert_eq!(result.warnings.len(), 1);
    assert!(project_markdown("unknown", "p", "P").is_err());
}

#[test]
fn accepts_method_versions_by_format_not_version_allowlist() {
    for version in ["2.9.0", "3.1.0", "4.5.3", "9.8.7"] {
        let run = project_markdown(&RECORD.replace("3.0.9", version), "p", "P").unwrap();
        assert_eq!(run["summary"]["slk_version"], version);
    }
}

#[test]
fn member_identity_alone_does_not_grant_creator_archival_authority() {
    let temp = tempfile::tempdir().unwrap();
    let record = temp.path().join("run.md");
    fs::write(
        &record,
        RECORD.replace("- 创建Supervisor：supervisor-a\n", ""),
    )
    .unwrap();
    assert!(register(
        &temp.path().join("sources"),
        &record,
        "p",
        "P",
        "supervisor-a"
    )
    .unwrap_err()
    .contains("CREATION_FACT_REQUIRED"));
}

#[test]
fn explicit_table_preserves_native_cell_ids_roles_and_planned_state() {
    let record = RECORD.replace("- 1：读取配置\n- 2：保存配置", "| CELL | 目标 | 状态 | 次数 |\n|---|---|---|---|\n| A.1 | 读取 | d1_passed | 1 |\n| A.2 | 保存 | planned | 0 |")
        .replace("| 角色 | 对话/任务ID | 状态 |", "| 角色 | 对话/任务ID | 状态 | Agent | 模型 | 推理 |")
        .replace("| Supervisor | supervisor-a | 保留 |", "| Supervisor | supervisor-a | 保留 | codex | gpt-6.1-sol | high |");
    let run = project_markdown(&record, "p", "P").unwrap();
    assert_eq!(run["go_nodes"][0]["cell_nodes"][1]["cell_id"], "A.2");
    assert_eq!(run["go_nodes"][0]["cell_nodes"][1]["state"], "planned");
    assert_eq!(run["roles"][0]["model"], "gpt-6.1-sol");
}

#[test]
fn database_failure_and_registered_markdown_are_isolated() {
    let temp = tempfile::tempdir().unwrap();
    let record = temp.path().join("run.md");
    fs::write(&record, RECORD).unwrap();
    register(
        &temp.path().join("bi-sources"),
        &record,
        "p",
        "P",
        "supervisor-a",
    )
    .unwrap();
    let config = temp.path().join("config.json");
    fs::write(&config, "not JSON").unwrap();
    let runs = slk_bi_desktop_lib::commands::runs_from(&config, None).unwrap();
    assert_eq!(runs["runs"][0]["run_id"], "R1");
    assert_eq!(runs["source_warnings"].as_array().unwrap().len(), 1);
    assert_eq!(fs::read_to_string(&config).unwrap(), "not JSON");
}
