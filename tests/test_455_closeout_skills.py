"""Post-D2 finalization is a separate reachable responsibility, not new D2."""

from scripts.local_package_metadata import EXPECTED_SKILLS
from tests.skill_testkit import ROOT, read_skill


def test_finalization_has_one_route_and_preserves_real_close_order():
    assert "slk-finalize-run" in EXPECTED_SKILLS
    assert "$slk-finalize-run" in read_skill("slk-close-run")
    final = read_skill("slk-finalize-run")
    assert final.index("总结") < final.index("terminal snapshot") < final.index("RUN_CLOSED")
    for marker in ("D2", "Supervisor", "共享", "未完成", "云端", "不重做", "ended-child"):
        assert marker in final
    assert "inspect-run-quiescence" in final
    assert "close-role" in final


def test_record_routes_summary_through_sealed_original_authority():
    record = read_skill("slk-record-run")
    assert "record-closeout-summary" in record
    assert "原创建 Supervisor" in record
    assert "公网出口 IP" in record
    assert "未获取" in record


def test_finalization_references_existing_single_machine_operations():
    final = read_skill("slk-finalize-run")
    assert "../slk-close-run/references/close-operations.md" in final
    assert "$slk-finalize-run" in read_skill("slk-archive-members")
    assert "$slk-finalize-run" in read_skill("slk-troubleshoot-run")
