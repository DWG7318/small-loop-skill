from __future__ import annotations

from pathlib import Path

from skill_testkit import (
    EXPECTED_CHILDREN,
    EXPECTED_SKILLS,
    ROOT,
    SKILLS,
    assert_skill_shape,
    read_skill,
    size_diagnostics,
)


def test_version_is_300() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "3.0.0"


def test_collection_has_one_main_and_twelve_children() -> None:
    actual = tuple(sorted(path.name for path in SKILLS.iterdir() if path.is_dir()))
    assert actual == tuple(sorted(EXPECTED_SKILLS))


def test_all_skills_have_discoverable_frontmatter_and_advisory_language() -> None:
    diagnostics: list[str] = []
    for name in EXPECTED_SKILLS:
        assert_skill_shape(name)
        diagnostics.extend(size_diagnostics(name, read_skill(name)))
    assert diagnostics == [], "\n".join(diagnostics)


def test_main_skill_keeps_the_owner_approved_core() -> None:
    text = read_skill("small-loop-skill")
    for marker in (
        "一个 Run",
        "线性",
        "Supervisor",
        "Checker",
        "Worker",
        "D0",
        "D1",
        "D2",
        "SLK-RUN-<RUN-ID>.md",
        "怎样继续",
        "按需激活",
    ):
        assert marker in text


def test_main_routes_to_every_child_once() -> None:
    text = read_skill("small-loop-skill")
    for child in EXPECTED_CHILDREN:
        assert text.count(f"`${child}`") == 1, child
    assert "`$slk-plan-cell`" not in text
    assert not (SKILLS / "slk-plan-cell").exists()


def test_active_skills_do_not_restore_the_legacy_topology() -> None:
    legacy = (
        "Control Conversation",
        "Verifier responsibility",
        "Run Patrol",
        "RUN_PATROL",
        "D3",
        "Owner Acceptance",
    )
    for name in EXPECTED_SKILLS:
        text = read_skill(name)
        for marker in legacy:
            assert marker not in text, f"{name}: {marker}"


def test_dispatch_execution_and_checking_keep_distinct_role_ownership() -> None:
    dispatch = read_skill("slk-dispatch-cell")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")
    assert "Checker" in dispatch and "Worker" in dispatch
    assert "Worker" in execute and "D0" in execute
    assert "Checker" in check and "D1" in check and "隔离" in check


def test_run_record_template_is_owned_by_record_skill() -> None:
    template = SKILLS / "slk-record-run" / "assets" / "SLK-RUN.template.md"
    assert template.is_file()


def test_no_legacy_root_skill_competes_with_collection() -> None:
    assert not (ROOT / "SKILL.md").exists()
    assert not (ROOT / "small-loop-skill" / "SKILL.md").exists()


def test_plan_run_derives_lean_checks_and_sizes_cells_for_available_capacity() -> None:
    text = read_skill("slk-plan-run")
    for marker in (
        "更新",
        "Run",
        "GO",
        "CELL",
        "D0",
        "D1",
        "D2",
        "项目",
        "相关检验 Skill",
        "减少重复",
        "过度检验",
        "每个 CELL",
        "初始 CELL",
        "初始估计",
        "实际施工事实",
        "创建 Supervisor 前",
        "模型",
        "电脑",
        "余量",
        "Owner",
        "$slk-grill-supervisor",
    ):
        assert marker in text
    assert "与 Owner 敲定 D0" not in text
    assert "推演" not in text
    assert "模拟" not in text


def test_supervisor_grill_checks_understanding_without_fixed_exam_or_stop() -> None:
    text = read_skill("slk-grill-supervisor")
    for marker in (
        "一次只问一个问题",
        "问题数量",
        "解释",
        "适用范围",
        "线性",
        "Supervisor",
        "Checker",
        "Worker",
        "D0",
        "D1",
        "D2",
        "通讯",
        "恢复",
        "允许误差",
        "豁免不等于 D1 通过",
        "后续 CELL",
        "按需激活",
        "日常 CELL",
        "D2 交接",
        "$slk-manage-team",
    ):
        assert marker in text


def test_manage_team_covers_visible_creation_recovery_tests_and_archive() -> None:
    text = read_skill("slk-manage-team")
    for marker in (
        "可见",
        "任务 ID",
        "原对话",
        "Supervisor",
        "Checker",
        "Worker",
        "双向通讯",
        "应急通道",
        "上一级",
        "接管",
        "归档 Worker",
        "归档 Checker",
        "状态",
    ):
        assert marker in text


def test_dispatch_cell_reality_checks_the_planned_cell_before_handoff() -> None:
    text = read_skill("slk-dispatch-cell")
    for marker in (
        "既定 CELL",
        "派发前",
        "模型",
        "电脑",
        "累积",
        "余量",
        "验收目标",
        "局部拆分",
        "CELL n/N",
        "$slk-execute-cell",
    ):
        assert marker in text


def test_dispatch_cell_is_checker_owned_and_worker_facing() -> None:
    text = read_skill("slk-dispatch-cell")
    for marker in (
        "Checker",
        "Worker",
        "目标",
        "范围",
        "D1",
        "相关上下文",
        "CELL n/N",
        "$slk-execute-cell",
    ):
        assert marker in text


def test_d1_pass_advances_to_the_next_preplanned_cell() -> None:
    text = read_skill("slk-check-cell")
    assert "$slk-dispatch-cell" in text
    assert "$slk-plan-cell" not in text


def test_checker_learns_cell_capacity_from_work_without_an_extra_gate() -> None:
    dispatch = read_skill("slk-dispatch-cell")
    check = read_skill("slk-check-cell")
    record = read_skill("slk-record-run")
    assert "前序 CELL 的实际施工" in dispatch
    assert "动态校准" in dispatch
    assert "容量事实" in check
    assert "不增加额外检查" in check
    assert "容量事实" in record


def test_execute_cell_delivers_d0_progress_record_and_checker_handoff() -> None:
    text = read_skill("slk-execute-cell")
    for marker in (
        "当前 CELL",
        "Worker",
        "最低 D0",
        "候选",
        "风险",
        "CELL n/N",
        "倒数第二项",
        "最后一项",
        "三次",
        "对话状态",
        "$slk-record-run",
        "$slk-check-cell",
        "$slk-recover-communication",
    ):
        assert marker in text


def test_check_cell_keeps_checker_isolation_and_d1_progress() -> None:
    text = read_skill("slk-check-cell")
    for marker in (
        "Checker",
        "隔离",
        "D1",
        "Worker",
        "验收目标",
        "独立",
        "D1 PASS：CELL n/N",
        "D1 FAIL：CELL n/N",
        "Supervisor",
        "$slk-record-run",
        "$slk-rework-cell",
    ):
        assert marker in text


def test_d1_delays_worker_d0_and_reasoning_until_independent_judgment() -> None:
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")
    record = read_skill("slk-record-run")
    assert "不进入初始 D1 交付" in execute
    assert "形成独立 D1 判断前" in check
    for marker in ("D0 结果", "判断过程", "建议关注点", "延后读取"):
        assert marker in check
    assert "D0 是输入" not in check
    assert "Worker 已说明的风险" not in check
    assert "D1 前" in record and "角色分区" in record


def test_record_run_preserves_role_history_failures_and_handoff_order() -> None:
    text = read_skill("slk-record-run")
    for marker in (
        "SLK-RUN-<RUN-ID>.md",
        "Supervisor",
        "Checker",
        "Worker",
        "各自",
        "错误",
        "返工",
        "豁免",
        "追加",
        "证据",
        "倒数第二项",
        "最后一项",
    ):
        assert marker in text
    template = SKILLS / "slk-record-run" / "assets" / "SLK-RUN.template.md"
    template_text = template.read_text(encoding="utf-8")
    for heading in (
        "# SLK Run",
        "## Run 定义",
        "## 成员",
        "## CELL 历史",
        "## 错误、返工与豁免",
        "## D2 交接",
        "## D2 与最终结果",
        "## 归档",
    ):
        assert heading in template_text
    assert template_text.index("#### 初始 D1 输入") < template_text.index(
        "#### Worker 施工记录（Checker形成独立D1判断后读取）"
    )
    assert template_text.index("## D2 交接") < template_text.index("## D2 与最终结果")


def test_supervisor_is_event_activated_not_a_daily_cell_controller() -> None:
    main = read_skill("small-loop-skill")
    grill = read_skill("slk-grill-supervisor")
    record = read_skill("slk-record-run")
    active = "\n".join(read_skill(name) for name in EXPECTED_SKILLS)
    for stale in (
        "Supervisor 维持 Run 连续推进",
        "Supervisor 怎样保持 Run 连续推进",
        "Supervisor 记录计划变化、GO 进展",
    ):
        assert stale not in active
    for marker in ("按需激活", "日常 CELL", "不在线等待"):
        assert marker in main
    assert "Checker 记录" in record and "GO 进度" in record
    assert "Supervisor 仅在被激活时记录" in record
    assert "按需激活" in grill


def test_rework_cell_keeps_checker_loop_and_offers_capability_or_split() -> None:
    text = read_skill("slk-rework-cell")
    for marker in (
        "D1 FAIL",
        "Checker",
        "Worker",
        "验收目标",
        "提高一级",
        "一分为二",
        "两轮",
        "Supervisor",
        "CELL n/N",
        "$slk-dispatch-cell",
        "$slk-execute-cell",
        "$slk-check-cell",
        "$slk-adjust-run",
    ):
        assert marker in text


def test_diagnose_defect_is_loaded_for_deeper_causal_work() -> None:
    text = read_skill("slk-diagnose-defect")
    for marker in (
        "复现",
        "未复现",
        "一个假设",
        "小实验",
        "根因",
        "最小修复",
        "回归",
        "风险相称",
        "$slk-rework-cell",
    ):
        assert marker in text


def test_adjust_run_keeps_supervisor_options_and_exemption_visible() -> None:
    text = read_skill("slk-adjust-run")
    for marker in (
        "Supervisor",
        "连续 D1",
        "D2",
        "提高一级",
        "电脑",
        "环境",
        "技术路线",
        "Owner",
        "豁免",
        "D1 PASS",
        "Run 目标",
        "验收目标",
        "$slk-dispatch-cell",
        "$slk-rework-cell",
    ):
        assert marker in text
    assert "把原 CELL 拆分为两个串行 CELL" not in text


def test_rework_reuses_the_dispatch_one_to_two_split() -> None:
    text = read_skill("slk-rework-cell")
    assert "$slk-dispatch-cell" in text
    assert "一分为二" in text


def test_recover_communication_uses_state_retries_and_upper_level_recovery() -> None:
    text = read_skill("slk-recover-communication")
    for marker in (
        "对话状态",
        "消息可见",
        "三次",
        "原始交付",
        "Worker → Supervisor → Checker",
        "上一级",
        "接管",
        "双向通讯测试",
        "$slk-manage-team",
    ):
        assert marker in text


def test_close_run_combines_d2_repair_archive_and_owner_conclusion() -> None:
    text = read_skill("slk-close-run")
    for marker in (
        "Supervisor",
        "D2",
        "全部 CELL",
        "GO",
        "衔接",
        "端到端",
        "关键风险",
        "Checker → Worker → Checker",
        "归档 Worker",
        "归档 Checker",
        "保留 Supervisor",
        "D0",
        "D1",
        "豁免",
        "Owner",
        "$slk-record-run",
        "$slk-manage-team",
        "$slk-adjust-run",
    ):
        assert marker in text


def test_d2_checks_the_combined_candidate_before_detailed_history() -> None:
    text = read_skill("slk-close-run")
    for marker in (
        "检查对象隔离",
        "先从 Run 目标",
        "最终候选",
        "端到端",
        "初步 D2 判断",
        "随后",
        "详细 D1 记录",
        "D1 PASS 不作为 D2 通过证明",
    ):
        assert marker in text
