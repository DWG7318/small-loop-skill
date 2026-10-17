"""3.1.1 document contracts; independent behavior exercises remain separate."""

from skill_testkit import ROOT, SKILLS, read_skill


def section(text: str, heading: str, level: int = 2) -> str:
    prefix = "#" * level + " "
    return text.split(prefix + heading, 1)[1].split("\n" + prefix, 1)[0]


def test_finalization_is_routed_after_d2_not_duplicated_in_old_skills():
    close = read_skill("slk-close-run")
    manage = read_skill("slk-manage-team")
    main = read_skill("small-loop-skill")
    for source in (close, manage, main):
        assert "$slk-finalize-run" in source
    assert "--bi-archive" not in close + manage
    assert "1. 调用 `$slk-record-run` 汇总最终" not in close
    assert "先真实归档 Worker、再真实归档 Checker" not in manage
    assert (SKILLS / "slk-finalize-run/SKILL.md").is_file()


def test_finalization_preserves_existing_acceptance_and_handles_only_remaining_work():
    path = SKILLS / "slk-finalize-run/SKILL.md"
    assert path.is_file(), "post-D2 finalization entry is missing"
    final = path.read_text(encoding="utf-8")
    for marker in (
        "准确 Run", "真实 D2", "终止", "不重做", "D0", "D1", "D2",
        "原工作簿", "结项总结", "唯一当前摘要", "CLOSED", "已完成项跳过",
        "准确任务 ID", "工程活动已结束", "Worker", "Checker", "外部任务",
        "创建 Supervisor", "--bi-read", "--bi-archive", "读取结果",
        "方法收尾", "本地归档", "云端保存", "待上传", "不重开工程",
        "未完成", "Owner", "保留 Supervisor",
    ):
        assert marker in final, marker
    assert final.index("结项总结") < final.index("--bi-read") < final.index("--bi-archive")
    for forbidden in ("inspect-run-quiescence", "close-overwatcher", "SLK.Run/SLK.Start", "RoleHost"):
        assert forbidden not in final


def test_member_activity_is_confirmed_ended_before_terminal_state_or_archive():
    final = read_skill("slk-finalize-run")
    confirmation = final.index("确认本 Run 的 Worker、Checker 工程活动已结束")
    assert confirmation < final.index("完成状态为 `CLOSED`") < final.index("--bi-archive")
    incomplete = final[confirmation:final.index("完成状态为 `CLOSED`")]
    assert "未确认结束" in incomplete
    assert "不进入成员归档或 BI 归档" in incomplete
    assert "不写终态" in incomplete


def test_public_summary_keeps_private_originals_out_of_bi_upload():
    summary = section(read_skill("slk-record-run"), "结项总结")
    assert "适合公开" in summary
    for private_content in ("账号密码", "访问令牌", "敏感日志", "私有路径"):
        assert private_content in summary
    assert "原始证据留在项目内" in summary
    assert "不新增逐份审批" in summary
    assert "不让 BI 改写" in summary


def test_original_workbook_has_one_structured_summary_with_author_and_time():
    template = (SKILLS / "slk-record-run/assets/SLK-RUN.template.md").read_text(encoding="utf-8")
    assert template.count("\n## 结项总结\n") == 1
    summary = section(template, "结项总结")
    assert "记录者" in summary and "实际平台" in summary and "任务身份" in summary
    assert "记录时间" in summary and "时区" in summary
    for heading in ("成果", "关键问题与现场处理", "剩余事项与证据"):
        assert f"### {heading}" in summary
    for marker in ("豁免", "已知原因", "未查明", "Supervisor", "结果", "风险", "证据"):
        assert marker in summary
    assert template.count("## 当前摘要") == 1


def test_device_signature_is_agent_supplied_not_a_bi_probe_or_gate():
    template = (SKILLS / "slk-record-run/assets/SLK-RUN.template.md").read_text(encoding="utf-8")
    definition = section(template, "Run 定义")
    for field in ("电脑名", "IP地址", "操作系统版本"):
        assert f"- {field}：" in definition
    record = read_skill("slk-record-run")
    for marker in ("执行 Agent", "公网出口 IP", "建议", "未获取", "BI 不探测"):
        assert marker in record
    assert "https://" not in definition


def test_summary_is_saved_before_bi_snapshot_with_append_only_corrections():
    bi = (SKILLS / "slk-record-run/references/bi.md").read_text(encoding="utf-8")
    assert "## 收尾与归档" in bi
    closeout = section(bi, "收尾与归档")
    assert closeout.index("保存") < closeout.index("--bi-read") < closeout.index("--bi-archive")
    for marker in ("结项总结", "创建 Supervisor", "读取", "待上传", "不重开工程", "追加更正", "来源", "历史 D2"):
        assert marker in closeout
    for marker in ("实际平台", "可信身份", "--supervisor", "不接收", "不探测"):
        assert marker in bi


def test_roles_and_model_names_are_not_brand_allowlists():
    models = read_skill("slk-select-models")
    for marker in ("职责", "不等同特定产品", "Owner", "实际 Agent", "不是白名单", "能力参考", "`gpt-6.1-sol` + `high`", "不应为轻量观察擅自降"):
        assert marker in models
    assert "当前推荐最低" not in models
    for name in ("slk-plan-run", "slk-grill-supervisor", "slk-manage-team"):
        assert "实际 Agent" in read_skill(name), name


def test_current_manifest_collection_tracks_added_finalize_without_a_permanent_quota():
    import json

    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    actual = {path.parent.name for path in SKILLS.glob("*/SKILL.md")}
    assert "slk-finalize-run" in actual
    assert manifest["version"] == "3.1.1"
    assert manifest["skill_count"] == len(actual)
    assert "skills/slk-finalize-run/SKILL.md" in {item["path"] for item in manifest["files"]}
