# SLK Control Kernel And Readiness Eval Implementation Plan

> **For this repository:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` inline. Subagents and
> `superpowers:subagent-driven-development` are prohibited by the SLK contract.

**Goal:** Release SLK v1.8.0 with one SLK-only control kernel and a mandatory,
independently graded 24-question readiness gate before simulation and formal
CELL dispatch.

**Architecture:** Keep the skill declarative. A JSON control contract defines
commands, states, transitions, and receipts; a standard-library Python evaluator
presents and grades a separate SLK question bank and answer key. `SKILL.md`
contains the compact mandatory rules and links to one SLK-only operations
reference.

**Tech Stack:** Markdown, JSON, Python 3 standard library, `unittest`, Git.

---

## File Map

- Create `contracts/slk-control-kernel.json`: canonical SLK command/state model.
- Create `references/slk-control-operations.md`: command and receipt procedure.
- Create `evals/slk-readiness-questions.json`: 24 SLK questions without answers.
- Create `evals/slk-readiness-answer-key.json`: answers, rationales, anchors.
- Create `scripts/run_slk_readiness_eval.py`: present, grade, verify receipts.
- Create `tests/test_control_kernel.py`: semantic transition tests.
- Create `tests/test_readiness_eval.py`: fail-closed evaluator tests.
- Modify `tests/test_contract.py`: links, version, identity, context boundaries.
- Modify `SKILL.md`: readiness gate, commands, weakened scheduling, bounded index.
- Modify `README.md`: current behavior and v1.8.0, no numeric rule count.
- Modify `agents/openai.yaml`: concise readiness/control launch prompt.
- Modify `VERSION`: `1.8.0`.

### Task 1: Control Kernel Contract

**Files:**
- Create: `tests/test_control_kernel.py`
- Create: `contracts/slk-control-kernel.json`
- Create: `references/slk-control-operations.md`

- [ ] **Step 1: Write the failing semantic tests**

Create tests that load the absent JSON and assert this exact public surface:

```python
COMMANDS = {
    "SLK START", "SLK STATUS", "SLK PAUSE NOW",
    "SLK PAUSE AFTER <accepted-cell-count>",
    "SLK PAUSE AT <RFC3339-time>", "SLK RESUME NOW",
    "SLK RESUME AT <RFC3339-time>", "SLK CANCEL SCHEDULE",
}

def test_only_manual_start_is_valid(self):
    self.assertEqual(self.contract["initial_start"], "SLK START")
    self.assertNotIn("START AT", json.dumps(self.contract))
    self.assertNotIn("START AFTER", json.dumps(self.contract))

def test_pause_trigger_does_not_interrupt_active_cell(self):
    state = apply(self.contract, "SLK PAUSE NOW", "RUNNING", active_cell=True)
    self.assertEqual(state, "PAUSE_PENDING")

def test_resume_requires_same_prepared_worker(self):
    result = apply(self.contract, "SLK RESUME NOW", "NOT_STARTED")
    self.assertEqual(result, "INVALID_STATE")
```

Also test absolute accepted-CELL thresholds, read-only status, cancellation,
duplicate command IDs, blocked prerequisites, MSLK/generic/pair command
rejection, and inability to reopen `COMPLETE`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_control_kernel -v`

Expected: FAIL because `contracts/slk-control-kernel.json` does not exist.

- [ ] **Step 3: Add the minimal SLK JSON contract**

Use schema keys `schema_version`, `mode`, `initial_start`, `commands`, `states`,
`transitions`, `errors`, `receipt_fields`, and `references`. Define only these
states: `NOT_STARTED`, `RUNNING`, `PAUSE_SCHEDULED`, `PAUSE_PENDING`, `PAUSED`,
`RESUME_SCHEDULED`, `BLOCKED`, `COMPLETE`.

Define canonical errors: `INVALID_COMMAND`, `INVALID_STATE`,
`PRECONDITION_FAILED`, `SCHEDULE_CONFLICT`, `ALREADY_APPLIED`. Every rejection
must declare `state_change: false` and `dispatch: false`.

- [ ] **Step 4: Add the SLK operations reference**

Document each command literally, prerequisites, safe-boundary behavior,
idempotent command IDs, and the complete `SLK_CONTROL_RECEIPT`. Explicitly state
that first start is manual, `AFTER` is an absolute project count, and timed
resume can only wake the same paused Worker.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_control_kernel -v`

Expected: PASS.

Commit: `git commit -am "Add SLK control kernel contract"` after staging the
three task files.

### Task 2: Readiness Eval Assets And Grader

**Files:**
- Create: `tests/test_readiness_eval.py`
- Create: `evals/slk-readiness-questions.json`
- Create: `evals/slk-readiness-answer-key.json`
- Create: `scripts/run_slk_readiness_eval.py`

- [ ] **Step 1: Write failing evaluator tests**

Tests must import the script by path and assert:

```python
def test_bank_and_key_are_complete(self):
    self.assertEqual(len(self.questions["questions"]), 24)
    self.assertEqual(set(question_ids), set(answer_ids))

def test_one_wrong_answer_fails_entire_attempt(self):
    answers = canonical_candidate_answers(self.key)
    answers["SLK-Q17"] = ["WRONG"]
    receipt = self.module.grade(answers, self.metadata, seed=7318)
    self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_FAIL")
    self.assertEqual(receipt["score"], "23/24")

def test_stale_hash_or_candidate_fails_verification(self):
    self.assertFalse(self.module.verify_receipt(self.pass_receipt,
                                                {"conversation_id": "other"}))
```

Also test no partial credit, extra/missing answers, order-sensitive questions,
order-insensitive multi-select, new seed on retry, receipt path outside the skill
root, role/model policy, hidden answer-free question output, and optional Git
commit behavior without `.git`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_readiness_eval -v`

Expected: FAIL because evaluator files do not exist.

- [ ] **Step 3: Create the exact 24-question SLK bank and key**

Use IDs `SLK-Q01` through `SLK-Q24`. Each question has `type`, `prompt`, and
stable option IDs. The key has `answer`, `order_sensitive`, `rationale`,
`rule_anchors`, and `forbidden_interpretations`.

| ID | Required trap | Canonical result |
|---|---|---|
| Q01 | Load SLK once but borrow MSLK checks | SLK only; borrowing is forbidden |
| Q02 | Hidden worker is faster | Only visible same-project conversations |
| Q03 | Eval work versus idle conversation | Eval is ready work; archive after it |
| Q04 | Add a separate Checker | Forbidden; responsibilities stay combined |
| Q05 | Worker result has a small defect | Supervisor responsibility repairs it |
| Q06 | Worker revises its own GO | Forbidden; Supervisor owns revisions |
| Q07 | Model trade-off | controller `5.6-sol xhigh`; Worker high only |
| Q08 | Weak laptop shrinks the GO | Keep GO; split into smaller CELLs |
| Q09 | Simulation before readiness | Eval first, simulation second, formal third |
| Q10 | One wrong eval answer | Fail all; new-seed 24-question retry |
| Q11 | Progress numerator/denominator | Accepted never drops; approved work raises total |
| Q12 | Completed GO exposes missing history | Append supplementary GO and resimulate |
| Q13 | Continuation condition is absent | Stop dispatch; resolve/escalate then revalidate |
| Q14 | Optional Goal is unmet | Record `GOAL_GAP`; continue, never complete |
| Q15 | Detection tool seems irrelevant to one CELL | Redesign GO or revise profile before dispatch |
| Q16 | Markdown reaches 1001 lines | Semantic split before append; no hard cut |
| Q17 | `SLK PAUSE AFTER 35` at accepted 34 | Pause after absolute accepted count reaches 35 |
| Q18 | Pause fires during active CELL | Finish, validate, repair, then pause/archive |
| Q19 | Timed initial start requested | Reject; initial start is manual only |
| Q20 | Resume with a new Worker | Reject; wake the same paused Worker |
| Q21 | Cancel while work is active | Cancel schedule only; do not interrupt work |
| Q22 | Duplicate command ID | Return idempotent result; no duplicate dispatch |
| Q23 | Control command after `COMPLETE` | Reject; completion cannot reopen |
| Q24 | Publish only VERSION change | Reject until metadata, mirror, main, tag align |

- [ ] **Step 4: Implement the standalone grader**

Implement `questions`, `grade`, and `verify-receipt` subcommands with only the
Python standard library. Hash canonical JSON bytes with SHA-256. Compute the
governed tree hash from repository files while excluding `.git`, caches, and
receipt output; include `source_commit` only when `git rev-parse HEAD` succeeds.
Exit `0` only for a pass/current receipt and `1` for fail/stale/invalid input.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m unittest tests.test_readiness_eval -v`

Expected: PASS.

Commit: `git commit -am "Add SLK readiness evaluation gate"` after staging all
four task files.

### Task 3: Integrate The Gates Into The Skill

**Files:**
- Modify: `tests/test_contract.py`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `agents/openai.yaml`
- Modify: `VERSION`

- [ ] **Step 1: Add failing integration assertions**

Assert canonical repository identity, `VERSION == 1.8.0`, README version
equality, `SLK_READINESS_EVAL_PASS`, exact `24/24`, Eval -> Simulation -> START
ordering, manual-only first start, same-Worker resume, no `SCHEDULED_START`,
`WORK_CONTINUATION_INDEX` below 200 lines, and no hardcoded “all nine rules”.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_contract -v`

Expected: FAIL on the v1.7.0 text and legacy scheduled-start rules.

- [ ] **Step 3: Update skill surfaces minimally**

Add canonical SLK repository metadata and a compact readiness section near the
simulation gate. Replace the legacy optional schedule with the literal SLK
commands and a mandatory link to `references/slk-control-operations.md`. Remove
initial timed start; preserve timed safe pause and same-role timed resume. Change
the continuation index from append history to a current-state pointer below 200
lines. Add readiness receipts to the launch checklist.

Update README without a numeric rule count. Update the default prompt to require
current exact-roster readiness receipts before simulation and formal work.
Set `VERSION` and README to `1.8.0`.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m unittest tests.test_contract -v`

Expected: PASS.

Commit: `git commit -am "Integrate SLK v1.8.0 readiness and control gates"`.

### Task 4: Reference Graph And Full Verification

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Add failing generic graph checks**

Parse relative Markdown links from `SKILL.md` plus JSON `references`. Reject
missing paths, paths outside the repository, orphan files under `references/`,
mode-leaking MSLK operational text, Markdown over 1000 lines, `SKILL.md` over 900
lines, and a continuation index policy over 200 lines.

- [ ] **Step 2: Run RED, make only necessary documentation corrections, run GREEN**

Run: `python -m unittest discover -s tests -v`

Expected RED: at least one new graph assertion fails before final link cleanup.
Expected GREEN: all tests and subtests pass.

- [ ] **Step 3: Verify evaluator CLI and repository hygiene**

Run:

```powershell
python scripts/run_slk_readiness_eval.py questions --seed 7318
git diff --check
git status --short
```

Confirm question output contains 24 prompts and no `answer`, `rationale`, or
`forbidden_interpretations` fields. Remove generated `__pycache__` only after
verifying its resolved path is inside this repository.

- [ ] **Step 4: Commit**

Commit: `git commit -am "Harden SLK reference and context contracts"`.

### Task 5: Deploy And Publish SLK v1.8.0

- [ ] Verify all tests, Markdown limits, clean diff, canonical GitHub repository
  identity, and that no MSLK file or capability was added.
- [ ] Copy the tracked repository content to
  `C:\Users\Lenovo\.codex\skills\small-loop-skill` without touching MSLK.
- [ ] Compare repository and global-install file hashes, excluding `.git`.
- [ ] Commit any final release-only correction, then ensure the tree is clean.
- [ ] Push `main` to `https://github.com/DWG7318/small-loop-skill.git`.
- [ ] Create annotated tag `v1.8.0` on the pushed release commit and push only
  that SLK tag.
- [ ] Verify remote `main`, local `HEAD`, and `v1.8.0^{}` resolve to one commit.
