from __future__ import annotations

import re
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


def test_version_is_current() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "4.2.7"


def test_collection_has_one_main_and_fourteen_children() -> None:
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
    assert "越靠后的 CELL" in text
    assert "衔接或融合工作的 CELL" in text
    assert "在可行时拆得更小" in text


def test_plan_run_keeps_inspection_out_of_the_cell_construction_plan() -> None:
    step = next(
        line
        for line in read_skill("slk-plan-run").splitlines()
        if line[:3].rstrip(". ").isdigit() and "D0" in line
    )
    for marker in ("D0", "D1", "D2", "检查本身", "独立 CELL", "检查发现", "工程工作"):
        assert marker in step
    assert step.index("D0") < step.index("D1") < step.index("D2") < step.index("检查本身")


def test_plan_run_reuses_existing_work_before_sizing_minimum_construction() -> None:
    text = read_skill("slk-plan-run")
    step = next(line for line in text.splitlines() if line.startswith("3. "))
    for marker in (
        "已完成或部分完成项目",
        "识别",
        "保留",
        "复用",
        "合理最小施工",
        "当前目标",
        "代码改动",
        "重复施工",
        "无关工作",
        "全局重构",
    ):
        assert marker in step
    assert "所有项目" not in step
    assert text.index("合理最小施工") < text.index("划分为初始 CELL")


def test_resource_guard_is_planned_before_models_and_cell_sizing() -> None:
    main = read_skill("small-loop-skill")
    plan = read_skill("slk-plan-run")
    grill = read_skill("slk-grill-supervisor")
    close = read_skill("slk-close-run")
    guard = read_skill("slk-guard-resources")

    assert main.count("`$slk-guard-resources`") == 1
    assert plan.index("CELL 结果") < plan.index("$slk-guard-resources")
    assert plan.index("$slk-guard-resources") < plan.index("$slk-select-models")
    assert plan.index("$slk-guard-resources") < plan.index("划分为初始 CELL")
    assert "Cargo" in grill and "独占资源" in grill
    assert "slk-cargo cleanup" in close
    assert "slk-cargo" in guard and "Cargo" in guard
    assert "CARGO_TARGET_DIR" not in main
    assert "RESOURCE_CONTENDED" not in main


def test_check_planning_prefers_product_evidence_not_a_checking_project() -> None:
    plan = read_skill("slk-plan-run")
    check = read_skill("slk-check-cell")
    for text in (plan, check):
        assert "现有" in text and "直接" in text
        assert "检查体系" in text
    assert "隔离不等于" in check
    assert "真实未覆盖风险" in check


def test_checker_separates_product_failure_from_checking_failures() -> None:
    check = read_skill("slk-check-cell")
    assert "检查工具或环境故障" in check
    assert "产品缺陷" in check
    assert "未证明" in check
    assert "不写为 PASS" in check
    assert "Supervisor" in check
    assert "D1 FAIL：CELL n/N" in check
    assert "D1 INCOMPLETE：CELL n/N" in check
    assert "零 finding" in check
    assert "只有 PASS 或 FAIL 闭合 D1" in check
    assert "不写 `D1_PASSED` 或 `D1_FAILED`" in check
    assert "TRANSPORT_FAILED" in check
    assert "同一 candidate 与 D1 attempt" in check
    assert "一次性 DSH/Worker 进程" in check


def test_426_worker_handoff_and_overwatcher_resume_are_exact_and_agent_first() -> None:
    execute = read_skill("slk-execute-cell")
    recover = read_skill("slk-recover-communication")
    overwatch = read_skill("slk-overwatch-run")
    main = read_skill("small-loop-skill")
    assert "代码、提交与测试完成不等于 Worker 角色完成" in execute
    assert "恰好一次当前 CELL/attempt/candidate" in execute
    assert "run+cell+attempt+candidate/message" in recover
    assert "不要先调用必然与现有 writer 冲突的 `thread/resume`" in recover
    assert "独立 headless Checker 传输宿主" in recover
    assert "`slk-state resume-overwatcher-turn`" in overwatch
    assert "新 Session、非 Supervisor 授权" in overwatch
    assert "4.2.7" in main


def test_d0_and_rework_use_relevant_checks_not_repeated_full_suites() -> None:
    execute = read_skill("slk-execute-cell")
    rework = read_skill("slk-rework-cell")
    assert "不提前重复 D1/D2" in execute
    assert "相关回归" in rework and "未受影响" in rework
    assert "有效" in rework


def test_d2_reuses_valid_facts_without_repeating_every_cell_or_building_a_framework() -> None:
    close = read_skill("slk-close-run")
    for marker in ("最终候选", "环境", "风险", "有效", "逐项重复 D1", "检查体系"):
        assert marker in close
    assert "建议最终核对：" not in close
    assert "D1 PASS 不作为 D2 通过证明" in close
    assert "Supervisor 后补证据不能替代 Checker 的 D1" in close


def test_recording_keeps_failure_history_without_recursive_proof_materials() -> None:
    record = read_skill("slk-record-run")
    for marker in ("错误", "返工", "豁免", "摘要", "路径", "当前节点", "原始证据", "实际执行", "推断"):
        assert marker in record


def test_known_misreadings_have_independent_negative_only_chapters() -> None:
    affected = (
        "small-loop-skill", "slk-plan-run", "slk-manage-team",
        "slk-dispatch-cell", "slk-execute-cell", "slk-check-cell",
        "slk-record-run", "slk-rework-cell", "slk-close-run",
    )
    for name in affected:
        text = read_skill(name)
        assert text.count("\n## 负面提示词\n\n") == 1, name
        section = text.split("\n## 负面提示词\n\n", 1)[1].split("\n## ", 1)[0]
        reminders = [line for line in section.splitlines() if line.strip()]
        assert reminders, name
        assert all(line.startswith("- 不要") for line in reminders), name
        assert len(reminders) == len(set(reminders)), name
        assert "释义：" not in section and "不要误解为" not in section, name
        assert "建议" not in section and "这里指" not in section, name


def test_supervisor_records_before_evidence_is_overwritten_without_becoming_patrol() -> None:
    record = read_skill("slk-record-run")
    positive = record.split("\n## 负面提示词\n\n", 1)[0]
    assert "继续调整前及时追加" in positive
    assert "关键失败" in positive and "未执行事项" in positive
    assert "保留可能被后续操作覆盖的必要证据" in positive
    assert "释义：" not in record
    assert "不要等到最后交接才补写" in record
    assert "不要把简要记录扩成逐命令审计" in record
    assert "Overwatcher 只写自己的运行观察" in record
    assert len(record.splitlines()) <= 42


def test_local_d0_attempts_are_distinct_from_checker_d1_rework() -> None:
    record = read_skill("slk-record-run")
    rework = read_skill("slk-rework-cell")
    assert "本地 D0 尝试" in record
    assert "OCRV Checker" in rework and "D1 FAIL" in rework
    assert "不要把 D0 草稿自修或 Checker 自建检查器故障计入 Worker 的 D1 返工次数" in rework
    assert "保留未受影响且仍有效的已完成工作" in rework
    assert "重复施工未受影响且仍有效的已完成工作" in rework


def test_select_models_matches_capability_to_each_visible_role() -> None:
    text = read_skill("slk-select-models")
    for marker in (
        "`gpt-5.6-sol` + `xhigh`",
        "Qwen3.8-Max",
        "DeepSeek V4 Flash",
        "ocrv-checker",
        "dsh-worker",
        "提示词自称某角色不构成绑定",
        "不自动把 DSH Worker 升级",
        "Owner 明确修订方法合同",
    ):
        assert marker in text
    for removed in ("gpt-5.6-terra", "gpt-5.6-luna", "模型升级阶梯"):
        assert removed not in text.split("## 负面提示词", 1)[0]
    assert "$slk-select-models" in read_skill("slk-plan-run")
    assert "$slk-select-models" not in read_skill("slk-adjust-run")


def test_optional_efficiency_tools_are_global_reusable_and_run_scoped() -> None:
    plan = read_skill("slk-plan-run")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")

    for marker in (
        "RTK",
        "Probe CLI",
        "Ponytail",
        "Codex 全域",
        "只安装一次",
        "安装不等于启用",
        "本次 Run",
        "Owner",
        "官方来源",
        "缺失或失败不阻止 SLK",
    ):
        assert marker in plan
    assert "自动 hook" in plan and "MCP" in plan and "额外 Agent" in plan
    assert "原始输出" in execute and "RTK" in execute and "Probe CLI" in execute
    assert "核心 diff" in check and "关键错误原文" in check
    assert "Probe CLI" in check and "RTK" in check


def test_efficiency_tools_do_not_replace_native_evidence_or_method_roles() -> None:
    plan = read_skill("slk-plan-run")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")

    assert "原生命令" in execute and "回退" in execute
    assert "原生命令" in check and "回退" in check
    assert "CELL 目标" in plan and "D0、D1、D2" in plan
    assert "不增加角色" in plan and "不增加流程层" in plan
    assert "Headroom" not in plan


def test_startup_order_and_creation_authority_are_unambiguous() -> None:
    main = read_skill("small-loop-skill")
    plan = read_skill("slk-plan-run")
    grill = read_skill("slk-grill-supervisor")
    record = read_skill("slk-record-run")
    manage = read_skill("slk-manage-team")

    assert plan.index("$slk-select-models") < plan.index("划分为初始 CELL")
    assert "原对话 ↔ Supervisor" in plan
    assert "Supervisor 创建 Checker，Checker 创建 Worker" in main
    assert "结构化角色 Eval" in main
    assert grill.index("$slk-record-run") < grill.index("$slk-manage-team")
    assert "通过 Eval 后" in record
    assert "$slk-manage-team" in record
    assert "复用" in manage and "不重复" in manage
    assert manage.index("Codex Supervisor 启动并登记 OCRV Checker") < manage.index(
        "Checker 理解确认"
    ) < manage.index("OCRV Checker 启动并登记 DSH Worker")
    assert "Worker 不重复完整方法问答" in manage


def test_fixed_role_models_are_not_overridden_during_rework() -> None:
    select = read_skill("slk-select-models")
    rework = read_skill("slk-rework-cell")
    assert "不在 CELL 之间自动换模型" in select
    assert "不自动把 DSH Worker 升级" in select
    assert "不自动替换 Worker" in rework
    assert "Owner 明确修订方法合同" in select


def test_d2_readiness_requires_d1_pass_or_supervisor_exemption() -> None:
    check = read_skill("slk-check-cell")
    close = read_skill("slk-close-run")

    for text in (check, close):
        assert "D1 PASS" in text
        assert "Supervisor 豁免" in text
    assert "获得 D1 结果或 Supervisor 豁免" not in check
    assert "当前 D1 结果或单独列出的 Supervisor 豁免" not in close
    assert "D1 PASS or Supervisor exemption" in close.split("---", 2)[1]


def test_communication_recovery_preserves_all_original_direct_routes() -> None:
    main = read_skill("small-loop-skill")
    dispatch = read_skill("slk-dispatch-cell")
    recover = read_skill("slk-recover-communication")
    manage = read_skill("slk-manage-team")

    assert "Worker 向 Checker" in main
    assert "$slk-recover-communication" in dispatch
    assert "真实激活" in dispatch and "后台" in dispatch
    assert "原发送者" in recover and "原有直连" in recover
    assert "Overwatcher" in recover and "必经 relay" in recover
    assert "handoff" in recover and "SUPERVISOR_DECISION_REQUIRED" in recover
    assert "subagent" in manage
    assert "不作为正式成员" in manage


def test_cross_agent_delivery_requires_native_activation() -> None:
    main = read_skill("small-loop-skill")
    transport = (ROOT / "docs/transport/SLK-TRANSPORT.md").read_text(encoding="utf-8")
    for marker in (
        "已登记的目标原生 Agent 入口",
        "原生 Agent 入口",
        "与消息匹配的原生启动证据",
        "不增加令牌专用回执",
        "旧 running、旧 TOKEN、可见消息或 heartbeat 都不证明正在工作",
    ):
        assert marker in main
    for marker in ("active writer", "not activation evidence", "does not claim the receiver or D2 started"):
        assert marker in transport


def test_every_internal_skill_reference_resolves_to_the_collection() -> None:
    import re

    known = set(EXPECTED_CHILDREN)
    for name in EXPECTED_SKILLS:
        references = set(re.findall(r"\$((?:slk-)[a-z-]+)", read_skill(name)))
        assert references <= known, f"{name}: {sorted(references - known)}"


def test_supervisor_eval_is_closed_versioned_and_runtime_bounded() -> None:
    text = read_skill("slk-grill-supervisor")
    for marker in (
        "SLK-ROLE-EVAL.v1.json",
        "8 个 runtime-critical 场景",
        "case-pack SHA-256",
        "validate_role_eval.py",
        "缺题",
        "重复题",
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
    assert "开放式长问答" in text
    assert "完整 40-case pack" in text


def test_manage_team_covers_native_role_creation_recovery_tests_and_archive() -> None:
    text = read_skill("slk-manage-team")
    for marker in (
        "可见",
        "任务 ID",
        "原对话",
        "Supervisor",
        "Checker",
        "Worker",
        "双向通讯",
        "D1_REWORK_DIRECTIVE",
        "上一级",
        "优先恢复原成员",
        "缺少回执不等于失效",
        "明确失效",
        "极端",
        "接管",
        "归档 Worker",
        "Worker、Checker",
        "状态",
        "原生 Agent 端点",
        "Codex Checker",
        "Codex Worker",
    ):
        assert marker in text
    assert "不要创建 Codex Checker 或 Codex Worker" in text


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
        "不增加接收回执轮次",
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
    assert "三个工程角色各写自己的事实" in record
    assert "Checker 的 D1 隔离" in record


def test_record_run_preserves_role_history_failures_and_handoff_order() -> None:
    text = read_skill("slk-record-run")
    for marker in (
        "SLK-RUN-<RUN-ID>.md",
        "Supervisor",
        "Checker",
        "Worker",
        "各写自己的事实",
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
        "Supervisor 记录计划变化、Run 进展",
    ):
        assert stale not in active
    for marker in ("按需激活", "日常 CELL", "结束当前活动", "wait_threads"):
        assert marker in "\n".join((main, read_skill("slk-manage-team")))
    assert "Checker 记录" in record and "Run 进度" in record
    assert "Supervisor 仅在被激活时记录" in record and "继续调整前及时追加" in record
    assert "按需激活" in grill


def test_rework_cell_uses_the_closed_supervisor_directive_path() -> None:
    text = read_skill("slk-rework-cell")
    for marker in (
        "D1 FAIL",
        "OCRV Checker",
        "Codex Supervisor",
        "同一 DSH Worker",
        "验收目标",
        "第三次 D1 FAIL",
        "D1_FAILURE_ESCALATION",
        "D1_REWORK_DIRECTIVE",
        "不重做或接管 D1",
        "一分为二",
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
        "固定角色绑定",
        "调整 CELL 或路线",
        "重新规划",
        "Owner 授权",
        "推荐方案",
        "最低必要授权",
        "技术路线",
        "同一 CELL",
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
        "slk-transport inspect",
        "message_id",
        "endpoint version",
        "payload SHA-256",
        "started.json",
        "retry-exact",
        "同一 `message_id`",
        "原发送者",
        "原有直连",
        "SUPERVISOR_DECISION_REQUIRED",
        "明确失效",
        "$slk-manage-team",
        "Overwatcher",
        "不 handoff",
        "最多原样重试一次",
    ):
        assert marker in text
    for forbidden in ("新消息", "更换 receiver", "轮询循环", "daemon", "无限 retry"):
        assert forbidden in text
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
        "各 CELL 结果",
        "衔接",
        "端到端",
        "关键风险",
        "Checker → Worker → Checker",
        "归档 Worker、Checker",
        "保留 Supervisor 对话",
        "Overwatcher",
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

    for marker in ("不使用正时长 `wait_threads`", "真实激活操作", "原生启动证据"):
        assert marker in main
    assert "不增加令牌专用回执" in dispatch and "发出完整 CELL 后结束本次激活" in dispatch
    assert "不读取Worker施工状态" in dispatch
    assert "候选交付重新激活Checker" in dispatch
    assert "发送后结束本轮Worker工作" in execute
    assert "不读取Checker状态" in execute
    assert "令牌到达即开始 D1" in execute
    assert "每次操作结束当前 turn" in recover
    assert "真实激活返回端点不可用" in recover
    assert "不重复激活" in recover
    assert "不读取其他成员内部状态" in manage
    assert "不跟踪下一对话" in record
    assert "Loop Engineering 的线性形态" in main
    assert "派发、施工与 D0、候选交付、隔离 D1" in main
    assert "D1 FAIL" in main and "D1 PASS" in main and "D2" in main
    assert "接收令牌不是 CELL 完工" in dispatch
    assert "接收令牌不结束当前 CELL 施工" in execute
    assert "一次发送完整 CELL，不把一个 CELL 拆成逐条命令派发" in dispatch
    assert "命令、工具结果或中间进展不构成 CELL 交付边界" in execute
    assert "完成整个 CELL 候选" in execute
    for stale in ("每完成一条命令就结束", "一条命令一次激活", "把下一条命令交给 Worker"):
        assert stale not in active
    assert "完成自己当前 Loop 节点" in manage


def test_optional_overwatcher_is_one_active_session_without_authority_or_relay() -> None:
    main = read_skill("small-loop-skill")
    manage = read_skill("slk-manage-team")
    watch = read_skill("slk-overwatch-run")
    recover = read_skill("slk-recover-communication")

    for marker in ("可选", "每 Run 最多一个", "不接管三角色通讯", "缺席不阻断工作"):
        assert marker in main
    for marker in ("同一 Session 不跨 Run 复用", "独立凭证", "不改变上述三角色直连"):
        assert marker in manage
    for marker in (
        "不直接改 BI",
        "180–300 秒",
        "前台 active turn",
        "八项",
        "不结束当前 turn",
        "exact retry",
        "归档本 Session",
        "不要成为第四个工程角色",
        "不要写 D0/D1/D2",
    ):
        assert marker in watch
    for forbidden in (
        "heartbeat",
        "automation",
        "cron",
        "Windows 计划任务",
        "daemon",
        "后台 Agent",
    ):
        assert f"不要创建 {forbidden}" in watch
    assert "每次检查后结束 turn" not in watch
    assert "低频、Run 专属唤醒" not in watch
    assert "必经 relay" in recover


def test_425_runtime_consistency_is_explicit_without_per_cell_watcher_confirmation() -> None:
    main = read_skill("small-loop-skill")
    watch = read_skill("slk-overwatch-run")
    recover = read_skill("slk-recover-communication")
    dispatch = read_skill("slk-dispatch-cell")
    execute = read_skill("slk-execute-cell")
    combined = "\n".join((main, watch, recover, dispatch, execute))

    for marker in (
        "commit-delivery-start",
        "runtime_revision",
        "started.json",
        "不可变 task file",
        "Git worktree",
        "wait-for-change",
    ):
        assert marker in combined
    for marker in (
        "一个 Run 只绑定一次",
        "不是每个 CELL 重新确认",
        "LATE 不等于 INACTIVE",
        "最后一轮",
        "CONTINUITY_RECOVERY_REQUIRED",
    ):
        assert marker in watch
    for forbidden in (
        "自动升级模型",
        "BoM 触发器",
        "旧信封作为新消息",
        "终态结果倒推启动成功",
    ):
        assert forbidden in combined


def test_run_identity_is_explicit_and_one_continuation_reuses_its_run_id() -> None:
    main = read_skill("small-loop-skill")
    negative = main.split("\n## 负面提示词\n\n", 1)[1]
    assert "按标题合并 Run" in negative
    assert "同一实际 Run 的继续过程中另造 run_id" in negative


def test_run_identity_recovery_and_method_adoption_are_explicit_and_append_only() -> None:
    main = read_skill("small-loop-skill")
    adjust = read_skill("slk-adjust-run")
    record = read_skill("slk-record-run")
    watch = read_skill("slk-overwatch-run")
    combined = "\n".join((main, adjust, record, watch))
    for marker in (
        "reconcile-run-identities",
        "adopt-method-contract",
        "canonical/source",
        "精确快照",
        "Owner 证据",
        "直接编辑 SQLite",
        "伪造",
        "新建替代 Run",
        "有效方法版本",
        "工程历史",
        "TOKEN",
    ):
        assert marker in combined
    assert "按标题自动合并 Run" in record
    assert "先绑定再补记录" in watch


def test_linear_loop_uses_one_registered_native_relay_token_without_a_new_subsystem() -> None:
    main = read_skill("small-loop-skill")
    for marker in (
        "进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`",
        "真实激活操作",
        "已登记的目标原生 Agent 入口",
        "与消息匹配的原生启动证据才证明流转",
        "同一 Run 最大且身份匹配的成功令牌才是当前事实",
        "不是新文件、角色、审批或外部状态系统",
        "只在既有 Loop 节点边界流转",
        "不增加令牌专用回执",
        "令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径",
    ):
        assert marker in main
    assert len(EXPECTED_SKILLS) == 15
    assert not any(path.name.startswith("slk-token") for path in SKILLS.iterdir())


def test_token_reports_responsibility_without_claiming_live_execution() -> None:
    main = read_skill("small-loop-skill")
    record = read_skill("slk-record-run")
    template = (SKILLS / "slk-record-run" / "assets" / "SLK-RUN.template.md").read_text(
        encoding="utf-8"
    )
    for marker in (
        "当前有效的 `SLK TOKEN`",
        "当前事实",
        "不证明正在工作",
        "旧 running",
        "活动无法证明",
    ):
        assert marker in "\n".join((main, read_skill("slk-overwatch-run")))
    assert "当前有效令牌" in record and "最后真实流转" in record
    assert "接收者在令牌激活本轮后的第一步" in record
    assert "先比较编号与身份" in record
    assert "同号或旧号不改指针" in record
    assert "不预写尚未发生的流转" in record
    assert "当前有效令牌" in template and "最后真实流转" in template


def test_existing_handoffs_move_the_same_token_between_existing_roles() -> None:
    main = read_skill("small-loop-skill")
    manage = read_skill("slk-manage-team")
    dispatch = read_skill("slk-dispatch-cell")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")
    adjust = read_skill("slk-adjust-run")
    close = read_skill("slk-close-run")
    recover = read_skill("slk-recover-communication")
    assert "Supervisor 用 `T001`" in main
    assert "SLK TOKEN T001" in manage
    assert "恢复原成员时重发原令牌编号" in manage
    assert "接管新成员确认后" in manage and "使旧令牌失效" in manage
    assert "Checker → Worker" in dispatch and "SLK TOKEN" in dispatch
    assert "Worker → Checker" in execute and "SLK TOKEN" in execute
    assert "Checker → Worker" in check and "Checker → Supervisor" in check
    assert "Supervisor → Checker" in adjust and "SLK TOKEN" in adjust
    assert "最终令牌" in close and "CLOSED" in close
    assert "同一 `message_id`" in recover and "新消息" in recover


def test_token_is_compact_monotonic_and_duplicate_safe() -> None:
    main = read_skill("small-loop-skill")
    dispatch = read_skill("slk-dispatch-cell")
    execute = read_skill("slk-execute-cell")
    record = read_skill("slk-record-run")
    for marker in (
        "令牌编号",
        "Run",
        "CELL",
        "当前节点",
        "接收者",
        "候选（如有）",
        "下一动作",
        "根记录路径",
    ):
        assert marker in dispatch
    assert "单调递增" in dispatch
    assert "相同或更旧的令牌编号" in execute and "不重开 CELL" in execute
    assert "真实激活操作" in main
    assert "同一 message、信封、端点和 scope 一次" in main
    assert "同号或旧号不改指针" in record
    assert "完整工程历史" in record and "不复制整段令牌历史" in record


def test_slk_rejects_goal_that_binds_one_conversation_as_the_run_driver() -> None:
    main = read_skill("small-loop-skill")
    negative = main.split("\n## 负面提示词\n\n", 1)[1]
    for marker in (
        "不要把 SLK Run 绑定到任何由单个对话持续工作到底的 Goal 模式",
        "不要让这类 Goal 驱动或续作 Run",
        "不限制目标定义",
        "固定对话",
        "Supervisor、Checker、Worker",
        "逐节点流转",
        "天然冲突",
    ):
        assert marker in negative
    assert "Codex Goal" not in negative
    for tool_name in ("create_goal", "get_goal", "update_goal"):
        assert tool_name not in negative


def test_cell_capacity_never_becomes_a_one_size_fits_all_rule() -> None:
    main = read_skill("small-loop-skill")
    negative = main.split("\n## 负面提示词\n\n", 1)[1]
    for marker in (
        "不要把针对某个 CELL、某类工作或一次经验形成的容量估计、数字边界或经验规则",
        "泛化为所有 CELL、整个 Run 或其他项目共同遵守的一刀切定额",
        "不要为了平均、整齐或便于管理",
        "要求每个 CELL 满足相同指标",
        "不排除根据具体 CELL 的目标、难度、依赖、模型、电脑和余量",
        "形成只适用于该 CELL 的、有事实依据的容量边界",
    ):
        assert marker in negative


def test_resource_prompt_surface_stays_out_of_the_main_router() -> None:
    main = read_skill("small-loop-skill")
    guard = read_skill("slk-guard-resources")

    for implementation_detail in (
        "CARGO_TARGET_DIR",
        "package cache",
        "Windows error 32",
        "RESOURCE_CONTENDED",
        "RESOURCE_RECOVERED",
    ):
        assert implementation_detail not in main
    assert "动态资源表" not in guard
    assert "巡检" not in guard
    assert "新角色" not in guard


def test_state_authority_is_bound_to_existing_roles_without_becoming_a_new_loop_layer() -> None:
    main = read_skill("small-loop-skill")
    record = read_skill("slk-record-run")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")
    adjust = read_skill("slk-adjust-run")
    close = read_skill("slk-close-run")
    resource = (
        SKILLS / "slk-execute-cell" / "references" / "resource-contention.md"
    )

    for marker in ("SQLite", "`slk-state`", "`slk-bi-query`", "只读", "三个角色"):
        assert marker in main
    for marker in ("中央 SLK 数据根", "自动导出", "SQLite", "三个工程角色", "Owner"):
        assert marker in record
    for text in (execute, check, adjust):
        assert "resource-contention.md" in text
    assert resource.is_file()
    resource_text = resource.read_text(encoding="utf-8")
    for marker in (
        "Cargo",
        "CARGO_TARGET_DIR",
        "不计入 D1 返工",
        "不推进 `SLK TOKEN`",
        "数据库",
        "端口",
        "GPU",
    ):
        assert marker in resource_text
    assert "D2" in close and "slk-state" in close
    assert "新角色" not in resource_text and "后台巡检" not in resource_text


def test_slk_public_method_is_run_then_cells_without_go() -> None:
    active = "\n".join(read_skill(name) for name in EXPECTED_SKILLS)
    template = (SKILLS / "slk-record-run" / "assets" / "SLK-RUN.template.md").read_text(
        encoding="utf-8"
    )
    assert "一个 SLK 对应一个 Run，Run 直接包含线性 CELL" in read_skill("small-loop-skill")
    assert "Run → CELL" in read_skill("slk-plan-run")
    assert re.search(r"\bGO\b", active) is None
    assert re.search(r"\bGO\b", template) is None


def test_fixed_native_role_topology_rejects_codex_substitution() -> None:
    main = read_skill("small-loop-skill")
    manage = read_skill("slk-manage-team")
    models = read_skill("slk-select-models")
    combined = "\n".join((main, manage, models))
    for marker in (
        "Codex = Supervisor",
        "OCRV = Checker",
        "DSH = Worker",
        "Qwen3.8-Max",
        "DeepSeek V4 Flash",
    ):
        assert marker in combined
    assert "不要创建 Codex Checker 或 Codex Worker" in manage
    positive = models.split("## 负面提示词", 1)[0]
    for forbidden in ("Luna xhigh → Terra high", "Terra high → Sol medium"):
        assert forbidden not in positive


def test_d1_incomplete_and_supervisor_rework_are_not_conflated() -> None:
    check = read_skill("slk-check-cell")
    rework = read_skill("slk-rework-cell")
    execute = read_skill("slk-execute-cell")
    assert "D1 INCOMPLETE" in check
    assert "Checker 保留 `SLK TOKEN`" in check
    assert "不触发返工" in check
    for marker in (
        "正式 D1 FAIL",
        "OCRV Checker",
        "Codex Supervisor",
        "Worker",
        "D1_REWORK_DIRECTIVE",
        "同一 CELL",
        "不重做或接管 D1",
    ):
        assert marker in rework + execute
    assert "BoM" not in rework + execute


def test_worker_and_checker_preflight_can_rationalize_locally_without_new_formal_units() -> None:
    main = read_skill("small-loop-skill")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")

    assert "角色本地轻量预检" in main
    assert "不能把内部顺序段当成正式 CELL 或 D1" in main
    assert "实现范围、依赖、工具能力、证据负荷" in execute
    assert "不能自行拆成多个正式 CELL" in execute
    assert "候选元数据、changed paths、验收条件、模型与工具能力" in check
    assert "D1-A/B/C" in check
    assert "仍只形成一个正式 D1" in check


def test_checker_does_not_turn_empty_review_or_missing_proof_into_pass() -> None:
    check = read_skill("slk-check-cell")
    negative = check.split("\n## 负面提示词\n\n", 1)[1]

    assert "缺少关键证明" in check and "INCOMPLETE" in check
    assert "实质产品缺陷" in check and "FAIL" in check
    assert "零 finding" in negative and "自动 PASS" in negative


def test_overwatcher_reports_worker_handoff_stall_then_pauses_for_same_member_recovery() -> None:
    overwatch = read_skill("slk-overwatch-run")

    assert "240 秒" in overwatch
    assert "报告 Supervisor" in overwatch
    assert "然后暂停" in overwatch
    assert "恢复原成员" in overwatch
