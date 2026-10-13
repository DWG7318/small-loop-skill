"""Check collection ownership and reachable guidance, not duplicated prose size."""

import re

from scripts.local_package_metadata import EXPECTED_SKILLS, read_version
from tests.skill_testkit import ROOT, read_skill, assert_skill_shape


NEW_RESPONSIBILITIES = {
    "slk-replace-member", "slk-archive-members",
    "slk-troubleshoot-preflight", "slk-troubleshoot-run",
}


def test_new_responsibilities_are_in_the_single_package_inventory():
    assert NEW_RESPONSIBILITIES <= set(EXPECTED_SKILLS)


def test_canonical_inventory_matches_the_delivered_skill_directories():
    actual = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    assert actual == set(EXPECTED_SKILLS)
    for name in EXPECTED_SKILLS:
        assert_skill_shape(name)


def test_main_has_one_discoverable_route_per_child():
    main = read_skill("small-loop-skill")
    for name in EXPECTED_SKILLS[1:]:
        assert main.count(f"`${name}`") == 1, name


def test_local_markdown_references_resolve_without_a_hidden_instruction_file():
    for name in EXPECTED_SKILLS:
        for source in (ROOT / "skills" / name).rglob("*.md"):
            for link in re.findall(r"\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
                if "://" in link or link.startswith("#"):
                    continue
                target = link.split("#", 1)[0].strip("<>")
                assert (source.parent / target).resolve().is_file(), (source, link)


def test_role_eval_stays_in_its_existing_asset_and_critical_case_count():
    # Runtime validation tests cover exact IDs, hashes, answers and revisions.
    import json
    asset = json.loads((ROOT / "skills/small-loop-skill/assets/SLK-ROLE-EVAL.v1.json").read_text(encoding="utf-8"))
    assert asset["method_version"] == read_version()
    counts = {}
    for case in asset["cases"]:
        if case.get("runtime_critical"):
            counts[case["role"]] = counts.get(case["role"], 0) + 1
    assert counts == {"supervisor": 8, "checker": 8, "worker": 8, "overwatcher": 8}


def test_run_record_template_keeps_isolated_d1_and_run_scoped_ow_archive():
    template = (ROOT / "skills/slk-record-run/assets/SLK-RUN.template.md").read_text(encoding="utf-8")
    assert template.index("#### 初始 D1 输入") < template.index("#### Worker 施工记录") < template.index("#### Checker D1")
    for section in ("## 错误、返工与豁免", "## D2 交接", "## D2 与最终结果", "## 归档", "## Owner 简报"):
        assert section in template
    assert "Overwatcher本Run绑定" in template
    assert "其他Run" in template
    assert "Overwatcher归档状态（若启用）" not in template
