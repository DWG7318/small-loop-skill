from __future__ import annotations

import json
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
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "4.4.2"


def test_collection_has_one_main_and_fourteen_children() -> None:
    actual = tuple(sorted(path.name for path in SKILLS.iterdir() if path.is_dir()))
    assert actual == tuple(sorted(EXPECTED_SKILLS))


def test_all_skills_have_discoverable_frontmatter_and_advisory_language() -> None:
    diagnostics: list[str] = []
    for name in EXPECTED_SKILLS:
        assert_skill_shape(name)
        diagnostics.extend(size_diagnostics(name, read_skill(name)))
    assert diagnostics == [], "\n".join(diagnostics)


def test_team_preflight_does_not_fabricate_an_ocrv_chat_session_or_eval() -> None:
    text = read_skill("slk-manage-team")
    assert "OCRV 没有任意提示/chat 入口" in text
    assert "runtime_root" in text
    assert "ocr llm test" in text


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


def test_supervisor_sizes_the_frozen_solution_for_dsh_before_dispatch() -> None:
    plan = read_skill("slk-plan-run")
    dispatch = read_skill("slk-dispatch-cell")
    for marker in (
        "工程方案和验收结果已经确定",
        "DSH Worker 的实际能力",
        "多个中小 CELL",
        "独立 D0",
        "独立 D1",
        "不改变原 Run 结果和验收强度",
    ):
        assert marker in plan
    for marker in ("派工前", "Supervisor", "DSH", "大 CELL", "拆分"):
        assert marker in dispatch
    assert "逐条命令" in dispatch


def test_plan_run_keeps_inspection_out_of_the_cell_construction_plan() -> None:
    step = next(
        line
        for line in read_skill("slk-plan-run").splitlines()
        if line[:3].rstrip(". ").isdigit() and "D0" in line
    )
    for marker in ("D0", "D1", "D2", "检查本身", "独立 CELL", "检查发现", "工程工作"):
        assert marker in step
    assert step.index("D0") < step.index("D1") < step.index("D2") < step.index("检查本身")


def test_cell_design_rejects_validation_only_cells_in_negative_prompts() -> None:
    for name in ("small-loop-skill", "slk-plan-run"):
        negative = read_skill(name).split("\n## 负面提示词\n\n", 1)[1]
        for marker in (
            "测试、复核、验收或独立检查本身",
            "施工 CELL",
            "D0/D1/D2",
            "重复检验",
        ):
            assert marker in negative, (name, marker)


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
    assert "实质产品缺陷为D1 FAIL" in check
    assert "导致未完成为D1 INCOMPLETE" in check
    assert "零 finding" in check
    assert "只有 PASS 或 FAIL 闭合 D1" in check
    assert "不写 `D1_PASSED` 或 `D1_FAILED`" in check
    assert "TRANSPORT_FAILED" in check
    assert "同一 candidate 与 D1 attempt" in check
    assert "一次性 DSH/Worker 进程" in check


def test_management_return_keeps_transport_and_candidate_attempts_distinct() -> None:
    for name in ("small-loop-skill", "slk-check-cell"):
        text = read_skill(name)
        for marker in ("管理消息 attempt", "原候选 attempt", "不能等同"):
            assert marker in text, (name, marker)


def test_426_worker_handoff_and_overwatcher_resume_are_exact_and_agent_first() -> None:
    execute = read_skill("slk-execute-cell")
    recover = read_skill("slk-recover-communication")
    overwatch = read_skill("slk-overwatch-run")
    main = read_skill("small-loop-skill")
    assert "代码完成与保存报告不等于交付" in execute
    assert "恰好一次当前 CELL/attempt/candidate" in execute
    assert "同一 candidate/message/attempt" in recover
    assert "不要在 active writer 前 resume" in recover
    assert "一次性Worker进程不托管OCRV长审查" in recover
    assert "任意 OW Session 退出" in overwatch
    assert "Supervisor 修复并提交匹配证据" in overwatch
    assert "4.4.2" in main


def test_retired_result_format_recovery_does_not_restart_or_replace_original_roles() -> None:
    recover = read_skill("slk-recover-communication")
    for marker in (
        "恢复已有通讯",
        "不重新施工或审查",
        "结果格式补交",
        "partial/context/terminal",
        "历史证据只读",
        "不能为模板重跑Agent",
        "不补造D0/D1/D2",
        "报告正文隐式触发副作用",
        "由Supervisor/OW代写Worker/Checker事实",
    ):
        assert marker in recover
    for retired in ("prepare-invalid-result-recovery", "consume-staged-checker-terminal"):
        assert retired not in recover


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
        "`gpt-6.1-sol`",
        "`high` 或 `xhigh`",
        "Luna 级",
        "`gpt-5.6-luna`、`gpt-6-luna`",
        "由 Owner 为每个 Run",
        "Qwen3.8-Max",
        "DeepSeek V4 Flash",
        "ocrv-checker",
        "dsh-worker",
        "提示词自称某角色不构成绑定",
        "不自动把 DSH Worker 升级",
        "Owner 明确修订方法合同",
    ):
        assert marker in text
    for removed in ("gpt-5.6-terra", "模型升级阶梯"):
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
    assert "Supervisor → Checker" in main and "Checker → Worker → Checker" in main
    assert "结构化角色 Eval" in main
    assert grill.index("$slk-record-run") < grill.index("$slk-manage-team")
    assert "通过 Eval 后" in record
    assert "$slk-manage-team" in record
    assert "复测受影响项" in manage
    assert manage.index("打开可见 BI 1.1.0") < manage.index(
        "登记 Owner 已确认的 Supervisor"
    ) < manage.index("用标准 headless 入口演练七条必要腿")
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

    assert "Checker → Worker → Checker" in main
    assert "$slk-recover-communication" in dispatch
    assert "原生进程" in dispatch and "后台消息" in dispatch
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
        "原生启动证据与 TOKEN 提交分别核实",
        "三工程角色不用正时长 `wait_threads`",
        "可见文本、旧 attempt/candidate 冒充当前活动",
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
    assert "完整 case pack" in text


def test_manage_team_covers_native_role_creation_recovery_tests_and_archive() -> None:
    text = read_skill("slk-manage-team")
    for marker in (
        "RUN_TEAM_REGISTRY",
        "agent identity",
        "session locator",
        "message endpoint",
        "delivery success signal",
        "打开可见 BI 1.1.0",
        "Supervisor",
        "Checker",
        "Worker",
        "Overwatcher",
        "七条必要腿",
        "真实发送者和接收者",
        "优先恢复原成员",
        "缺少回执不等于失效",
        "明确失效",
        "replace-role",
        "退役旧记录",
        "close-role",
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
        "保存完整原件并独立发给Checker",
        "真实接收",
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
        "D1 PASS",
        "D1 FAIL",
        "slk_checker_decide(verdict, message?)",
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
        "已有输出先保存并独立投递",
        "记录/ACK/Temporal维护失败不扣报告",
        "工程交接另核实真实接收启动与原子TOKEN提交",
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
    for marker in ("按需激活", "逐 CELL", "结束活动", "wait_threads"):
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
        "第二次连续 D1 FAIL",
        "D1_FAILURE_ESCALATION",
        "D1_REWORK_DIRECTIVE",
        "不重做或接管 D1",
        "多个中小后继 CELL",
        "CELL n/N",
        "$slk-dispatch-cell",
        "$slk-execute-cell",
        "$slk-check-cell",
        "$slk-adjust-run",
        "Debug Skill",
        "$superpowers:systematic-debugging",
    ):
        assert marker in text


def test_second_consecutive_d1_failure_requires_supervisor_cell_split() -> None:
    combined = "\n".join((
        read_skill("slk-rework-cell"),
        read_skill("slk-adjust-run"),
        read_skill("small-loop-skill"),
    ))
    for marker in (
        "原则上最多一次常规 D1 FAIL",
        "绝大部分 CELL 首轮 D1 PASS",
        "第二次连续 D1 FAIL",
        "应停止普通返工",
        "进一步拆分",
        "多个中小后继 CELL",
        "独立 D0",
        "独立 D1",
        "不改变原目标和验收强度",
    ):
        assert marker in combined
    assert "第三次 D1 FAIL 后先重新规划" not in read_skill("slk-rework-cell")


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
    assert "多个中小后继 CELL" in text


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
    for forbidden in ("新消息", "endpoint/receiver", "轮询循环", "daemon", "无限 retry"):
        assert forbidden in text
    assert "Owner/Main 真实激活" in text
    assert "原对话" not in text


def test_432_desktop_recovery_documents_windows_invocation_and_attempt_root() -> None:
    text = read_skill("slk-recover-communication")
    assert "PowerShell 用 `python <slk-transport.pyz>`" in text
    assert "不要用 `& <slk-transport.pyz>`" in text
    assert "`--attempt-root` 是 attempts 根目录" in text
    assert "不是 `<run_id>/<message_id>`" in text
    assert "平台回读" in text and "可见文字" in text


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

    for marker in ("不用正时长 `wait_threads`", "真实激活操作", "原生启动证据"):
        assert marker in main
    assert "不增加令牌专用回执" in dispatch and "原子提交成功后结束本次激活" in dispatch
    assert "不读取 Worker 施工状态" in dispatch
    assert "候选交付重新激活 Checker" in dispatch
    assert "原生启动证据完成原子提交后结束当前活动" in execute
    assert "不继续停留或读取 Checker 状态" in execute
    assert "可信Host保存完整原件并独立发给Checker" in execute
    assert "每次操作结束当前 turn" in recover
    assert "真实激活返回端点不可用" in recover
    assert "不重复激活" in recover
    assert "不使用 `wait_threads`" in manage
    assert "不跟踪下一对话" in record
    assert "Loop Engineering 的线性形态" in main
    assert "派发、施工与 D0、候选交付、隔离 D1" in main
    assert "D1 FAIL" in main and "D1 PASS" in main and "D2" in main
    assert "接收令牌不是 CELL 完工" in dispatch
    assert "接收令牌不结束当前 CELL 施工" in execute
    assert "一次发送完整 CELL，不把一个 CELL 拆成逐条命令派发" in dispatch
    assert "命令、工具结果或中间进展不构成 CELL 交付边界" in execute
    assert "完整 CELL 候选交付" in execute
    for stale in ("每完成一条命令就结束", "一条命令一次激活", "把下一条命令交给 Worker"):
        assert stale not in active
    assert "完成当前节点和必要交接后结束活动" in manage


def test_required_overwatcher_is_one_role_per_run_without_authority_or_relay() -> None:
    main = read_skill("small-loop-skill")
    manage = read_skill("slk-manage-team")
    watch = read_skill("slk-overwatch-run")
    recover = read_skill("slk-recover-communication")

    for marker in ("每个 Run 都登记", "一个 Run 只绑定一个", "不改 BI", "不改", "D0/D1/D2"):
        assert marker in main
    for marker in ("独立角色实例", "同一精确 OW Session 可服务多个 Run", "不代发施工消息"):
        assert marker in manage
    for marker in (
        "不写 BI/TOKEN",
        "600 秒",
        "同一前台 turn",
        "仍继续观察",
        "不代发日常消息",
        "不恢复成员",
        "不要写 BI、TOKEN",
    ):
        assert marker in watch
    for forbidden in (
        "heartbeat",
        "automation",
        "cron",
        "计划任务",
        "daemon",
        "后台 Agent",
    ):
        assert forbidden in watch
    assert "不要因报告成功而暂停或退出" in watch
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
        "每个 Run 绑定一个 OW role instance",
        "同一精确 OW Session 可以服务多个 Run",
        "600 秒",
        "1200 秒",
        "runtime guard",
    ):
        assert marker in watch
    for forbidden in (
        "自动升级模型",
        "新增协议、daemon",
        "旧信封换成新消息",
        "终态倒推启动",
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
    assert "同一精确 OW Session 可以服务多个 Run" in watch


def test_linear_loop_uses_one_registered_native_relay_token_without_a_new_subsystem() -> None:
    main = read_skill("small-loop-skill")
    for marker in (
        "进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`",
        "真实激活操作",
        "已登记的目标原生 Agent 入口",
        "原生启动证据与 TOKEN 提交分别核实",
        "同一 Run 最大且身份匹配的成功令牌才是当前事实",
        "不是新文件、角色、审批或外部状态系统",
        "只在既有 Loop 节点边界流转",
        "令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径",
    ):
        assert marker in main
    assert "不增加令牌专用回执" in read_skill("slk-dispatch-cell")
    assert len(EXPECTED_SKILLS) == 16
    assert not any(path.name.startswith("slk-token") for path in SKILLS.iterdir())


def test_dispatch_documents_closed_supervisor_to_checker_wrapper() -> None:
    dispatch = read_skill("slk-dispatch-cell")
    assert "worker_endpoint" in dispatch
    assert "worker_payload" in dispatch
    assert "不要把 Worker payload 直接放在 CELL_DISPATCH 顶层" in dispatch


def test_token_reports_responsibility_without_claiming_live_execution() -> None:
    main = read_skill("small-loop-skill")
    record = read_skill("slk-record-run")
    template = (SKILLS / "slk-record-run" / "assets" / "SLK-RUN.template.md").read_text(
        encoding="utf-8"
    )
    for marker in (
        "当前有效的 `SLK TOKEN`",
        "当前事实",
        "不构成真实运行证明",
        "界面 running",
        "无法证明",
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
    assert "当前权威序列的下一枚单调递增 `SLK TOKEN`" in manage
    assert "已有首轮交接不重派首 CELL" in manage
    assert "恢复原成员时重发原令牌编号" in manage
    assert "接管新成员确认后" in manage and "使旧令牌失效" in manage
    assert "Checker → Worker" in dispatch and "SLK TOKEN" in dispatch
    assert "Worker → Checker" in execute and "SLK TOKEN" in execute
    assert "Checker → Worker" in check and "Checker → Supervisor" in check
    assert "Supervisor → Checker" in adjust and "SLK TOKEN" in adjust
    assert "最终令牌" in close and "CLOSED" in close
    assert "同一 `message_id`" in recover and "新消息" in recover


def test_terminal_engineering_roles_require_central_close_evidence_before_archive_claim() -> None:
    manage = read_skill("slk-manage-team")
    close = read_skill("slk-close-run")
    combined = "\n".join((manage, close))
    for marker in (
        "`slk-state close-role`",
        "lifecycle=exited",
        "display_state=archived",
        "active endpoint",
    ):
        assert marker in combined
    assert "计划归档" in combined and "已经归档" in combined
    assert "Supervisor 保留" in combined
    assert "Overwatcher" in combined and "close-overwatcher" in combined


def test_440_terminal_order_closes_overwatcher_before_run_and_engineering_roles() -> None:
    close = read_skill("slk-close-run")
    overwatch = read_skill("slk-overwatch-run")
    assert (
        "D2_PASSED → terminal snapshot → OW final cycle → close-overwatcher → "
        "RUN_CLOSED → close-role"
    ) in close
    assert "D2_PASSED" in overwatch and "RUN_CLOSED" in overwatch


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
        assert marker in main
    for marker in ("令牌编号", "Run", "CELL", "当前位置 `n/N`", "接收者", "下一动作", "根记录路径"):
        assert marker in dispatch
    assert "单调递增" in dispatch
    assert "相同或更旧的令牌编号" in execute and "不重开 CELL" in execute
    assert "真实激活操作" in main
    assert "exact retry 只沿原消息一次" in main
    assert "同号或旧号不改指针" in record
    assert "完整工程历史" in record and "不复制整段令牌历史" in record


def test_preparation_goal_exception_does_not_bind_the_whole_run() -> None:
    main = read_skill("small-loop-skill")
    negative = main.split("\n## 负面提示词\n\n", 1)[1]
    for marker in (
        "用于启动准备／预检之外", "Supervisor", "团队准备子 Skill",
        "CELL、D0、D1、返工、OW 巡查、D2", "整 Run",
    ):
        assert marker in negative
    team = read_skill("slk-manage-team")
    for marker in ("Owner 已授权", "续用", "不重复建立", "CELL01", "原生启动", "合法 TOKEN",
                   "OW", "无未闭合", "可恢复错误", "最后可信", "简明准备记录", "不是自动重启",
                   "工具不可用", "预算", "不能擅自暂停", "Owner 明确暂停", "证据保留"):
        assert marker in team


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
    assert "D1_INCOMPLETE_ESCALATION" in check
    assert "把 TOKEN 交给 Supervisor" in check
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
    assert "REWORK_REQUESTED" in rework
    assert "state event" in rework
    assert "transport payload" in rework


def test_worker_and_checker_preflight_can_rationalize_locally_without_new_formal_units() -> None:
    main = read_skill("small-loop-skill")
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")

    assert "角色本地轻量预检" in main
    assert "不能把内部顺序段当成正式 CELL 或 D1" in main
    assert "实现范围、依赖、工具能力、证据负荷" in execute
    assert "不能自行拆成多个正式 CELL" in execute
    assert "候选元数据、changed paths、验收条件、模型与工具能力" in check
    assert "不自动切段" in check
    assert "仍只形成一个正式 D1" in check


def test_checker_does_not_turn_empty_review_or_missing_proof_into_pass() -> None:
    check = read_skill("slk-check-cell")
    negative = check.split("\n## 负面提示词\n\n", 1)[1]

    assert "缺少关键证明" in check and "INCOMPLETE" in check
    assert "实质产品缺陷" in check and "FAIL" in check
    assert "零 finding" in negative and "自动 PASS" in negative


def test_overwatcher_reports_anomaly_and_continues_observing_without_recovery_authority() -> None:
    overwatch = read_skill("slk-overwatch-run")

    assert "600 秒" in overwatch
    assert "报告 Supervisor" in overwatch
    assert "仍继续观察" in overwatch
    assert "不恢复成员" in overwatch


def test_lost_overwatcher_write_credential_rotates_the_same_exact_binding() -> None:
    overwatch = read_skill("slk-overwatch-run")
    manage = read_skill("slk-manage-team")
    combined = "\n".join((overwatch, manage))

    for marker in (
        "rotate-overwatcher-credential",
        "overwatcher_write_credential",
        "overwatcher_credential_id",
        "authenticate-role",
        "Session",
        "turn",
        "binding",
    ):
        assert marker in combined
    assert "非秘密 `overwatcher_credential_id`" in manage
    assert "不伪造 cycle" in combined
    assert "直接改数据库" in combined


def test_overwatcher_truth_check_and_temporal_guard_mapping_are_unambiguous() -> None:
    overwatch = read_skill("slk-overwatch-run")
    manage = read_skill("slk-manage-team")
    combined = "\n".join((overwatch, manage))

    for marker in (
        "inspect-native-activity",
        "UNKNOWN",
        "CLEAR",
        "ANOMALY",
        "交叉核对",
        "1200 秒",
        "runtime guard",
        "FOREGROUND_ACTIVE_TURN",
    ):
        assert marker in combined


def test_worker_held_cycle_requires_one_read_only_completion_inspection() -> None:
    overwatch = read_skill("slk-overwatch-run")
    for marker in (
        "Worker 持有 TOKEN",
        "恰好一次",
        "inspect-worker-completion",
        "无凭据",
        "只读",
        "当前 Run/CELL/attempt/message",
        "缺少 `WORK_STARTED` 不能单独证明",
    ):
        assert marker in overwatch


def test_terminal_overwatcher_cycle_keeps_minimal_hash_bound_evidence() -> None:
    overwatch = read_skill("slk-overwatch-run")

    for marker in (
        "证据路径",
        "SHA-256",
        "terminal snapshot",
        "final cycle",
        "close-overwatcher",
        "RUN_CLOSED",
    ):
        assert marker in overwatch


def test_4210_forbids_post_turn_self_wake_and_fixed_time_promises() -> None:
    main = read_skill("small-loop-skill")
    supervisor = read_skill("slk-grill-supervisor")
    recovery = read_skill("slk-recover-communication")
    combined = "\n".join((main, supervisor, recovery))

    for marker in (
        "post-turn",
        "延迟脚本",
        "固定秒数",
        "不改旧证据",
        "Owner/Main 真实激活",
    ):
        assert marker in combined
    assert "不用post-turn延迟脚本或固定秒数承诺自动恢复" in recovery
    assert "后台自唤醒" in combined


def test_4210_worker_checker_and_resource_corrections_are_explicit() -> None:
    execute = read_skill("slk-execute-cell")
    check = read_skill("slk-check-cell")
    resources = read_skill("slk-guard-resources")

    for marker in ("密封 Checker endpoint/envelope", "evidence index", "原始日志路径"):
        assert marker in execute
    assert "SLK_DSH_INSTANCE_ID" not in execute
    assert "SLK_DSH_SESSION_ID" not in execute
    for marker in (
        "一个正式 D1",
        "低严重性观察",
        "不能机械判为 FAIL",
        "process exit",
        "JSON parse",
        "business status",
    ):
        assert marker in check
    assert "sandbox SID" in resources
    assert "同一安全命令会话" in resources


def test_440_overwatcher_continues_after_reports_and_has_one_supervisor_target() -> None:
    overwatch = read_skill("slk-overwatch-run")

    for marker in (
        "负责对象只有登记的 Supervisor",
        "正常时继续观察",
        "仍继续观察",
        "final cycle",
        "close-overwatcher",
        "归档 Session",
    ):
        assert marker in overwatch
    for marker in (
        "同一前台 turn",
        "不要因报告成功而暂停或退出",
        "不要等待 Supervisor 回复",
        "不要重复发送没有新事实的同一告警",
    ):
        assert marker in overwatch


def test_440_temporal_is_required_but_keeps_engineering_authority_outside_workflows() -> None:
    main = read_skill("small-loop-skill")
    manage = read_skill("slk-manage-team")
    temporal = read_skill("slk-manage-temporal")
    combined = "\n".join((main, manage, temporal))

    for marker in (
        "本地共享",
        "SLK.Start",
        "SLK.Run",
        "slk.native-start/v2",
        "不判断 CELL",
        "D0/D1/D2",
        "TOKEN",
        "不派首 CELL",
        "下一 CELL 保持阻断",
    ):
        assert marker in combined


def test_442_existing_desktop_ow_uses_trusted_read_only_attestation_and_live_audits() -> None:
    overwatch = read_skill("slk-overwatch-run")
    temporal = read_skill("slk-manage-temporal")
    combined = "\n".join((overwatch, temporal))

    for marker in (
        "attest-desktop-overwatcher",
        "slk.desktop-overwatcher-attestation/v1",
        "platform_input_item_id",
        "slk.native-start/v2",
        "desktop-overwatcher-attestation",
        "每次 1200 秒审计重新调用",
        "read_thread",
        "不发送消息",
        "不调用模型",
        "不建 daemon",
    ):
        assert marker in combined
    assert "native-activity.json` 的旧时间" in combined


def test_430_role_eval_covers_temporal_start_authority_and_recovery_boundaries() -> None:
    pack = json.loads(
        (ROOT / "skills/small-loop-skill/assets/SLK-ROLE-EVAL.v1.json").read_text(
            encoding="utf-8-sig"
        )
    )
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-TEMPORAL-REQUIRED-READY",
        "CHK-TEMPORAL-NO-D1",
        "WRK-TEMPORAL-NATIVE-START",
        "OVW-TEMPORAL-REPORT-ONLY",
    } <= case_ids


def test_worker_remains_flash_without_pro() -> None:
    main = read_skill("small-loop-skill")
    models = read_skill("slk-select-models")
    combined = "\n".join((main, models))

    assert "DeepSeek V4 Flash" in combined
    assert "DeepSeek V4 Pro" not in combined


def test_optional_features_use_the_declared_catalog() -> None:
    main = read_skill("small-loop-skill")
    plan = read_skill("slk-plan-run")

    assert "未登记功能不能靠任意 ON/OFF" in main
    assert "Ponytail、RTK、Probe CLI" in plan
    assert "Supervisor 可补充项目所需 Skill/Tool" in plan
    assert "Overwatcher 与 Temporal 是 4.4.2 readiness 必需项" in plan


def test_431_context_restoration_revalidates_authoritative_run_facts() -> None:
    main = read_skill("small-loop-skill")

    for marker in (
        "上下文压缩",
        "中央状态",
        "当前 Run 记录",
        "当前 TOKEN",
        "摘要、旧话题或对话记忆",
        "停止串题",
    ):
        assert marker in main


def test_checker_explicit_action_replaces_post_d1_suffix_without_expanding_authority() -> None:
    main = read_skill("small-loop-skill")
    rework = read_skill("slk-rework-cell")

    assert "slk_checker_decide" in main
    assert "slk_checker_decide(FAIL, message?)" in rework
    assert "不再使用 `--slk-post-d1`" in rework
    assert "同一次标准工具调用内部" in rework
    assert "DESKTOP_BRIDGE_REQUIRED" in rework
    assert "密封 Checker 凭据" in rework
    assert "空闲 Supervisor 走正常直达" in rework


def test_442_runtime_binding_migration_is_routed_and_fail_closed() -> None:
    main = read_skill("small-loop-skill")
    adjust = read_skill("slk-adjust-run")

    assert "旧 Checker 端点迁移" in main
    for marker in (
        "prepare-runtime-binding-migration",
        "migrate-runtime-binding",
        "RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION",
        "supervisor-admin revise-plan",
        "slk-runtime-binding-migration.schema.json",
        "不要派发下一 CELL",
        "Owner 明确冻结有限预算",
    ):
        assert marker in adjust
