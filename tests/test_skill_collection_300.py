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


def test_collection_has_one_main_and_thirteen_children() -> None:
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
    ):
        assert marker in text


def test_main_routes_to_every_child_once() -> None:
    text = read_skill("small-loop-skill")
    for child in EXPECTED_CHILDREN:
        assert text.count(f"`${child}`") == 1, child


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


def test_plan_run_covers_method_update_capacity_acceptance_and_optional_simulation() -> None:
    text = read_skill("slk-plan-run")
    for marker in (
        "更新",
        "Run",
        "GO",
        "CELL",
        "D0",
        "D1",
        "D2",
        "模型",
        "电脑",
        "余量",
        "推演",
        "Owner",
        "$slk-grill-supervisor",
    ):
        assert marker in text


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
