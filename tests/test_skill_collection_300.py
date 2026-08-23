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
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "3.0.3"


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
    assert "`$slk-diagnose-defect`" not in text
    assert not (SKILLS / "slk-diagnose-defect").exists()


def test_every_child_declares_its_slk_only_usage_boundary() -> None:
    boundary = (
        "> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，"
        "不可脱离 SLK Run 单独使用。\n"
        "> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill "
        "或同集合流程路由到本情境。"
    )
    for child in EXPECTED_CHILDREN:
        text = read_skill(child)
        frontmatter, body = text[4:].split("\n---\n", 1)
        assert "Small Loop Skill (SLK) Run" in frontmatter, child
        assert boundary in body, child
        assert body.index(boundary) < body.index("## "), child

    assert boundary not in read_skill("small-loop-skill")
    design = (
        ROOT
        / "docs/superpowers/specs/2026-08-22-slk-lightweight-skill-collection-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs/superpowers/plans/2026-08-22-slk-3.0.0-lightweight-skill-collection.md"
    ).read_text(encoding="utf-8")
    assert "不可脱离 SLK Run 单独使用" in design
    assert "不可脱离 SLK Run 单独使用" in plan


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


def test_select_models_matches_capability_to_each_visible_role() -> None:
    text = read_skill("slk-select-models")
    for marker in (
        "Supervisor",
        "Checker",
        "Worker",
        "专业编程",
        "独立审查",
        "降低一级",
        "不能太低",
        "提高一级",
        "CELL",
        "电脑",
        "可替换",
        "记录",
        "Owner 可以直接指定",
        "不违反本 Skill",
        "不因偏离建议层级",
        "相应调整 CELL",
        "不擅自替换",
        "规划阶段",
        "施工中",
    ):
        assert marker in text
    assert "$slk-select-models" in read_skill("slk-plan-run")
    assert "$slk-select-models" in read_skill("slk-adjust-run")


def test_startup_order_and_creation_authority_are_unambiguous() -> None:
    main = read_skill("small-loop-skill")
    plan = read_skill("slk-plan-run")
    grill = read_skill("slk-grill-supervisor")
    record = read_skill("slk-record-run")
    manage = read_skill("slk-manage-team")

    assert plan.index("$slk-select-models") < plan.index("划分为初始 CELL")
    assert "原对话 ↔ Supervisor" in plan
    assert "Supervisor 创建 Checker，Checker 创建 Worker" in main
    assert "Checker 职责理解确认" in main
    assert grill.index("$slk-record-run") < grill.index("$slk-manage-team")
    assert "通过 Grill 后" in record
    assert "$slk-manage-team" in record
    assert "复用" in manage and "不重复" in manage
    assert manage.index("Supervisor 创建 Checker") < manage.index(
        "Checker 理解确认"
    ) < manage.index("Checker 创建 Worker")
    assert "Worker 不重复完整方法问答" in manage


def test_owner_specified_models_are_not_overridden_during_rework() -> None:
    select = read_skill("slk-select-models")
    rework = read_skill("slk-rework-cell")
    adjust = read_skill("slk-adjust-run")

    assert "Owner 已指定" in select
    for text in (rework, adjust):
        assert "Owner 已指定" in text
        assert "由 Owner 决定" in text
    assert "返回当前调整" in select


def test_d2_readiness_requires_d1_pass_or_supervisor_exemption() -> None:
    check = read_skill("slk-check-cell")
    close = read_skill("slk-close-run")

    for text in (check, close):
        assert "D1 PASS" in text
        assert "Supervisor 豁免" in text
    assert "获得 D1 结果或 Supervisor 豁免" not in check
    assert "当前 D1 结果或单独列出的 Supervisor 豁免" not in close
    assert "D1 PASS or Supervisor exemption" in close.split("---", 2)[1]


def test_communication_recovery_routes_only_the_worker_checker_handoff() -> None:
    main = read_skill("small-loop-skill")
    dispatch = read_skill("slk-dispatch-cell")
    recover = read_skill("slk-recover-communication")
    manage = read_skill("slk-manage-team")

    assert "Worker 向 Checker" in main
    assert "$slk-manage-team" in dispatch and "恢复原 Worker" in dispatch
    assert "真实激活" in dispatch and "后台" in dispatch
    assert "Worker" in recover.split("---", 2)[1]
    assert "Checker" in recover.split("---", 2)[1]
    assert "派发、施工、D1或D2节点" not in recover
    assert "subagent" in manage
    assert "不作为正式成员" in manage


def test_every_internal_skill_reference_resolves_to_the_collection() -> None:
    import re

    known = set(EXPECTED_CHILDREN)
    for name in EXPECTED_SKILLS:
        references = set(re.findall(r"\$((?:slk-)[a-z-]+)", read_skill(name)))
        assert references <= known, f"{name}: {sorted(references - known)}"


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
        "推荐方案",
        "最低必要授权",
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
        "优先恢复原成员",
        "缺少回执不等于失效",
        "明确失效",
        "极端",
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
        "真实激活",
        "明确回执",
        "Supervisor",
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
    for marker in ("按需激活", "日常 CELL", "结束当前活动", "wait_threads"):
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
        "Debug Skill",
        "$superpowers:systematic-debugging",
    ):
        assert marker in text


def test_adjust_run_keeps_supervisor_authority_and_d1_exemption_clear() -> None:
    text = read_skill("slk-adjust-run")
    for marker in (
        "Supervisor",
        "连续 D1",
        "D2",
        "提高一级",
        "Owner 授权",
        "推荐方案",
        "最低必要授权",
        "技术路线",
        "同一 CELL",
        "两轮 D1",
        "后续 CELL",
        "豁免",
        "D1 PASS",
        "Run 目标",
        "验收目标",
        "$slk-dispatch-cell",
        "$slk-rework-cell",
    ):
        assert marker in text
    assert "把原 CELL 拆分为两个串行 CELL" not in text
    assert "更换电脑、工具、账号或测试环境" not in text
    assert "向 Owner 提出一个清楚的问题" not in text
    assert "其余 Run" not in text
    assert "Supervisor 调整模型、电脑" not in read_skill("small-loop-skill")


def test_rework_reuses_the_dispatch_one_to_two_split() -> None:
    text = read_skill("slk-rework-cell")
    assert "$slk-dispatch-cell" in text
    assert "一分为二" in text


def test_recover_communication_requires_real_activation_and_preserves_checker() -> None:
    text = read_skill("slk-recover-communication")
    for marker in (
        "send_message_to_thread",
        "后台聊天记录",
        "状态变化",
        "明确回执",
        "原始交付",
        "Worker → Supervisor → Checker",
        "优先恢复原 Checker",
        "缺少回执不等于",
        "明确失效",
        "极端",
        "接管 Checker",
        "干净的 D1 恢复信封",
        "恢复原 Checker 任务",
        "不是新 CELL",
        "已收到，开始检查：CELL n/N",
        "Worker 任务 ID",
        "根记录",
        "Worker 原始 D1 交付原文",
        "Supervisor 不加入",
        "D0 结果",
        "判断过程",
        "建议关注点",
        "Supervisor 自己的结论",
        "通讯故障过程",
        "Checker → Worker",
        "结束本次激活",
        "双向通讯测试",
        "$slk-manage-team",
    ):
        assert marker in text
    assert "消息可见且目标对话正在活动" not in text
    assert "三次不同方式" not in text
    assert "Owner" not in text
    assert "原对话" not in text


def test_close_run_combines_d2_repair_archive_and_owner_conclusion() -> None:
    text = read_skill("slk-close-run")
    for marker in (
        "Supervisor",
        "D2",
        "所有计划 CELL",
        "明确处理结果",
        "D1 PASS",
        "Supervisor 豁免",
        "不把豁免改写为完成",
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
    assert "全部 CELL 完成后" not in text
    assert "全部 CELL 完成后" not in read_skill("small-loop-skill")
    assert "全部完成时" not in read_skill("slk-check-cell")


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


def test_roles_end_their_turn_instead_of_waiting_on_or_watching_peers() -> None:
    main = read_skill("small-loop-skill")
    dispatch = read_skill("slk-dispatch-cell")
    execute = read_skill("slk-execute-cell")
    recover = read_skill("slk-recover-communication")
    manage = read_skill("slk-manage-team")
    record = read_skill("slk-record-run")
    active = "\n".join(read_skill(name) for name in EXPECTED_SKILLS)

    for stale in (
        "等待候选交付",
        "本次激活后新出现的施工状态",
        "工作状态变化，才构成接收证据",
        "有界确认窗口",
        "不在线等待",
    ):
        assert stale not in active

    for marker in ("不使用`wait_threads`", "结束当前活动", "真实消息重新激活"):
        assert marker in main
    assert "明确回执说明交付已接收" in dispatch
    assert "不读取Worker施工状态" in dispatch
    assert "候选交付重新激活Checker" in dispatch
    assert "发送后结束本轮Worker工作" in execute
    assert "不读取Checker状态" in execute
    assert "异步重新激活Worker" in execute
    assert "发送后结束当前活动" in recover
    assert "平台明确返回不可用" in recover
    assert "不读取Checker的D1过程" in recover
    assert "不读取其他成员内部状态" in manage
    assert "不跟踪下一对话" in record
    assert "Loop Engineering 的线性形态" in main
    assert "派发、施工与 D0、候选交付、隔离 D1" in main
    assert "D1 FAIL" in main and "D1 PASS" in main and "D2" in main
    assert "回执只确认交付已接收，不结束 Worker 当前 CELL 的施工" in dispatch
    assert "接收回执不结束当前 CELL 施工" in execute
    assert "一次发送完整 CELL，不把一个 CELL 拆成逐条命令派发" in dispatch
    assert "命令、工具结果或中间进展不构成 CELL 交付边界" in execute
    assert "完成整个 CELL 候选" in execute
    for stale in ("每完成一条命令就结束", "一条命令一次激活", "把下一条命令交给 Worker"):
        assert stale not in active
    assert "完成自己当前 Loop 节点" in manage


def test_wait_clarification_does_not_add_skill_lines() -> None:
    expected = {
        "slk-adjust-run": 40,
        "slk-check-cell": 36,
        "slk-close-run": 53,
        "slk-dispatch-cell": 44,
        "slk-execute-cell": 30,
        "slk-grill-supervisor": 39,
        "slk-manage-team": 52,
        "slk-plan-run": 35,
        "slk-record-run": 36,
        "slk-recover-communication": 64,
        "slk-rework-cell": 26,
        "slk-select-models": 39,
        "small-loop-skill": 41,
    }
    actual = {name: len(read_skill(name).splitlines()) for name in EXPECTED_SKILLS}
    assert actual == expected
