from skill_testkit import read_skill


def test_d2_repairs_are_cause_based_not_a_model_failure_counter():
    models = read_skill("slk-select-models")
    adjust = read_skill("slk-adjust-run")
    assert "同一 GO 第一次 D2 返工" not in models + adjust
    assert "同一 GO 第二次 D2" not in models + adjust
    for marker in ("D2", "实际原因", "能力", "Owner"):
        assert marker in models and marker in adjust
    assert "第二次 D1 返工" in models  # Existing D1 escalation is not changed.


def test_turn_end_does_not_authorize_duplicate_cargo_work_or_global_kill():
    recovery = read_skill("slk-recover-communication")
    for marker in ("回合结束不等于", "外部任务", "任务 ID", "归属", "原结果", "不全局结束", "最后动作"):
        assert marker in recovery


def test_bi_uses_existing_record_and_does_not_add_4x_runtime():
    record = read_skill("slk-record-run")
    assert "预编译" in record and "1.1.6" in record
    assert "创建 Supervisor" in record
    assert "不改写工程结论" in record
    assert "Temporal" not in record and "Overwatcher" not in record
