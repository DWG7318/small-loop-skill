# SLK Loop Engineering Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct SLK's identity to the linear form of Loop Engineering and remove the receipt-versus-work ambiguity with the smallest possible replacements.

**Architecture:** Keep the existing 13-Skill collection and all role boundaries. Replace three main-Skill sentences and the directly affected dispatch, execute, and team-management sentences; add semantic assertions to the existing test module and propagate patch version 3.0.2 through existing carriers.

**Tech Stack:** Markdown Skills, Python `pytest`, repository validator, Skill quick validator.

---

### Task 1: Lock the Loop identity and receipt semantics

**Files:**
- Modify: `tests/test_skill_collection_300.py`
- Modify: `skills/small-loop-skill/SKILL.md`
- Modify: `skills/slk-dispatch-cell/SKILL.md`
- Modify: `skills/slk-execute-cell/SKILL.md`
- Modify: `skills/slk-manage-team/SKILL.md`

- [ ] **Step 1: Add failing semantic assertions to the existing wait-clarification test**

Require the existing loaded texts to contain these exact meanings:

```python
assert "Loop Engineering 的线性形态" in main
assert "派发、施工与 D0、候选交付、隔离 D1" in main
assert "D1 FAIL" in main and "D1 PASS" in main and "D2" in main
assert "回执只确认交付已接收，不结束 Worker 当前 CELL 的施工" in dispatch
assert "接收回执不结束当前 CELL 施工" in execute
assert "完成自己当前 Loop 节点" in manage
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/test_skill_collection_300.py::test_roles_end_their_turn_instead_of_waiting_on_or_watching_peers -q`

Expected: FAIL because the Loop Engineering and receipt markers are absent.

- [ ] **Step 3: Make only sentence replacements in the four Skills**

Use these meanings without adding sections or Skill lines:

```text
SLK 是 Loop Engineering 的线性形态；一个 SLK 对应一个 Run，GO 与 CELL 线性推进。
CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1；D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。
回执只确认交付已接收，不结束 Worker 当前 CELL 的施工。
接收回执不结束当前 CELL 施工。
成员完成自己当前 Loop 节点并完成交接后结束活动；消息只传输 Loop 工作和结果。
```

- [ ] **Step 4: Run focused test and confirm GREEN**

Run: `python -m pytest tests/test_skill_collection_300.py::test_roles_end_their_turn_instead_of_waiting_on_or_watching_peers -q`

Expected: `1 passed`.

- [ ] **Step 5: Confirm Skill line counts did not grow**

Run: `python -m pytest tests/test_skill_collection_300.py::test_wait_clarification_does_not_add_skill_lines -q`

Expected: `1 passed` with the existing 13-file line-count map unchanged.

### Task 2: Propagate patch identity and validate

**Files:**
- Modify: `VERSION`
- Modify: `MANIFEST.json`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CHANGELOG.md`
- Modify: `VALIDATION-REPORT.md`
- Modify: `scripts/validate_repository.py`
- Modify: `tests/test_repository_300.py`
- Modify: `tests/test_skill_collection_300.py`

- [ ] **Step 1: Change only current-version carriers from 3.0.1 to 3.0.2**

Keep all historical `3.0.1` changelog content. Add one `3.0.2` changelog entry describing the Loop identity and receipt clarification. Recompute only affected Manifest SHA-256 entries using the repository's existing manifest convention.

- [ ] **Step 2: Run the full repository gates**

Run:

```powershell
python scripts/validate_repository.py
python scripts/quick_validate.py skills
python -m pytest -q
python -O -m pytest -q
git diff --check
```

Expected: repository PASS, 13 Skill directories PASS, all tests PASS in normal and optimized Python, and no diff errors.

- [ ] **Step 3: Commit the implementation candidate**

```powershell
git add CHANGELOG.md MANIFEST.json README.md README.zh-CN.md VALIDATION-REPORT.md VERSION scripts/validate_repository.py skills tests
git commit -m "fix: define SLK as linear Loop Engineering"
```
