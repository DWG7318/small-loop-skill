"""Guidance contracts at their owning Skill, not duplicate prose requirements.

Exact Eval, runtime state, transport and lifecycle behavior stay in their
existing suites. These source checks are not real engineering acceptance.
"""
from __future__ import annotations

import re
import pytest

from scripts.local_package_metadata import EXPECTED_SKILLS, read_version
from tests.skill_testkit import EXPECTED_CHILDREN, ROOT, assert_skill_shape, read_skill

# Topic, authoritative guide, required semantic anchors. Technical references
# are checked separately; no fixed size, line count or Skill-count gate.
POLICIES = [
    ("linear-method", "small-loop-skill", ("一个Run", "顺序CELL", "Owner明确")),
    ("normal-chain", "small-loop-skill", ("Supervisor→Checker→Worker→Checker",)),
    ("fail-chain", "small-loop-skill", ("Checker→Supervisor→同一Worker→Checker",)),
    ("three-engineering-roles", "small-loop-skill", ("OCRVChecker", "DSHWorker", "CodexSupervisor")),
    ("d0-d1-d2", "small-loop-skill", ("D0是Worker", "D1是原Checker", "D2是Supervisor")),
    ("beijing-advice", "small-loop-skill", ("北京时间UTC\\+8", "18:00", "22:00", "不作.*门槛")),
    ("ow-no-authority", "small-loop-skill", ("只观察", "不干预", "不写BI/TOKEN/工程事实")),
    ("optional-goal", "small-loop-skill", ("准备Goal由Supervisor按需使用", "不占用无关Goal", "不驱动整个Run")),
    ("current-preparation", "small-loop-skill", ("不等待首CELL或首cycle", "不重演历史全链")),
    ("originals-without-cap", "small-loop-skill", ("SHA-256", "完整读原件", "不设任意字符上限")),
    ("last-action", "small-loop-skill", ("最后的任务动作", "随后结束", "未闭合只续原交接")),
    ("no-role-wait", "small-loop-skill", ("三工程角色不用正时长wait_threads", "post-turn")),
    ("monotonic-token", "small-loop-skill", ("一个当前有效SLKTOKEN", "单调编号", "相同或更旧TOKEN不重开")),
    ("real-start", "small-loop-skill", ("slk.native-start/v2", "终态.*不是启动证明")),
    ("not-free-text", "small-loop-skill", ("显式认证", "不得退回自由文本")),
    ("compact-revalidate", "small-loop-skill", ("压缩续作", "中央Run", "CELL/attempt", "不串题")),
    ("no-check-cell", "slk-plan-run", ("检验本身不列施工CELL",)),
    ("reuse-work", "slk-plan-run", ("保留、复用已有", "合理最小施工", "不等于.*最小diff")),
    ("contextual-capacity", "slk-plan-run", ("DSH当前模型能力", "返工余量", "不冻结统一容量定额")),
    ("integration-size", "slk-plan-run", ("衔接/融合", "更小")),
    ("lean-checks", "slk-plan-run", ("已有测试/构建/运行入口", "D0、D1、D2", "不先搭检查项目")),
    ("product-evidence", "slk-plan-run", ("直接证据入口", "间接验证不冒充目标环境实测")),
    ("owner-before-team", "slk-plan-run", ("Owner确认方案及Supervisor人选", "一次初始化")),
    ("optional-tools", "slk-plan-run", ("RTK", "ProbeCLI", "Ponytail", "全域安装一次", "不自动安装")),
    ("no-auto-hooks", "slk-plan-run", ("不用自动hook/MCP/额外Agent", "回原文或原生命令")),
    ("resource-plan", "slk-guard-resources", ("静态检查", "无特别资源安排", "不要.*持续观察")),
    ("resource-same-node", "slk-guard-resources", ("同一节点恢复", "保留当前SLKTOKEN")),
    ("model-owner", "slk-select-models", ("Owner决定", "gpt-6.1-sol", "high/xhigh", "Qwen3.8-Max", "DeepSeekV4Flash")),
    ("ow-model-example", "slk-select-models", ("仅推荐", "不是Luna系列白名单", "低推理开销")),
    ("no-model-escalation", "slk-select-models", ("D1FAIL不自动升级Worker", "Owner明确修订")),
    ("same-eval", "slk-grill-supervisor", ("8个runtime-critical", "当前身份/revision/case-packSHA-256", "validate_role_eval.py")),
    ("affected-understanding", "slk-grill-supervisor", ("只重新确认受影响理解", "未变理解及答案可复用", "旧artifact.*新实测")),
    ("not-extra-exam", "slk-grill-supervisor", ("不是运行时额外考试", "重复考试")),
    ("init-once", "slk-manage-team", ("一次init-run", "已有Run读回原身份", "随后Supervisor建立/指定OCRVChecker")),
    ("creation-authority", "slk-manage-team", ("由Checker建立/指定DSHWorker", "不创建CodexChecker/Worker")),
    ("identity-registry", "slk-manage-team", ("RUN_TEAM_REGISTRY", "agentidentity", "native/sessionlocator", "设备", "deliverysuccesssignal")),
    ("current-admission", "slk-manage-team", ("preflight-new-run", "preflight-admission", "不读取历史conformance", "NOT_READY")),
    ("visible-bi", "slk-manage-team", ("打开可见BI1.1.1", "共享服务/本Run工作流", "一次当前OWACTIVE")),
    ("ocrv-not-fake-eval", "slk-manage-team", ("不假造Eval", "MCP", "runtime_root", "nativestart/result")),
    ("original-channel", "slk-manage-team", ("脚本/OW补救代发不算正常通路", "已有精确投递才用")),
    ("retain-preparation", "slk-manage-team", ("不重复已完成项", "不重做已完成项", "建议耗时不是截止线")),
    ("restore-before-replace", "slk-replace-member", ("先恢复", "没有回复", "不是成员失效", "Supervisor必须由Owner确认")),
    ("replacement-history", "slk-replace-member", ("replace-role", "旧令牌失效", "保留旧记录")),
    ("same-child-rebind", "slk-replace-member", ("rebind-session", "同一直属child", "endpointversion")),
    ("credential-not-child", "slk-replace-member", ("rotate-overwatcher-credential", "overwatcher_write_credential", "不是重建child")),
    ("true-archive", "slk-archive-members", ("ROLE_CLOSED", "display_state=archived", "Supervisor保留")),
    ("shared-child-survives", "slk-archive-members", ("解除此Run不停止child", "二次确认停止", "不关闭.*共享服务")),
    ("preflight-recipes", "slk-troubleshoot-preflight", ("可选排障入口", "不是.*自动裁决器", "新问题可直接调查")),
    ("no-message-no-recovery", "slk-troubleshoot-preflight", ("已有精确消息才用", "不必创造消息")),
    ("run-recipes", "slk-troubleshoot-run", ("可选", "不是.*必经层", "Supervisor可.*选择、组合")),
    ("resume-original-node", "slk-troubleshoot-run", ("原节点/operation", "不重复准备、施工或D0/D1/D2")),
    ("dispatch-calibration", "slk-dispatch-cell", ("前序施工/D0/D1", "不另设容量检查", "退回Supervisor")),
    ("dispatch-wrapper", "slk-dispatch-cell", ("CELL_DISPATCH", r"\{worker_endpoint,worker_payload\}", "不把Worker内容放在顶层")),
    ("exact-next", "slk-dispatch-cell", ("--slk-complete-d1", "精确下一RequiredCELL", "D2_READY")),
    ("atomic-dispatch", "slk-dispatch-cell", ("不可变taskfile", "commit-delivery-start", "唯一runtime_revision")),
    ("worker-preflight", "slk-execute-cell", ("本地预检", "common-dir", "64字符", "不造candidate")),
    ("internal-segments", "slk-execute-cell", ("不另建CELL/TOKEN", "不并行Worker", "最低D0")),
    ("worker-action", "slk-execute-cell", ("SLK_WORKER_ACTION_COMMAND", "submit-worker-action", "CANDIDATE_SUBMITTED")),
    ("d0-isolation", "slk-execute-cell", ("Worker事实与证据分区", "不拼进初始D1背景", "完整报告仍独立保存")),
    ("no-format-rerun", "slk-execute-cell", ("非JSON", "非零退出", "不触发格式补交或重跑")),
    ("full-candidate", "slk-check-cell", ("完整候选", "跨文件核对全部CELL目标", "不按组多次提交D1")),
    ("external-original", "slk-check-cell", ("slk_read_evidence", "无工具长度上限", "路径已发不等于已读")),
    ("d1-independent", "slk-check-cell", ("延后读Worker", "独立初步判断后", "客观原件")),
    ("checker-decision", "slk-check-cell", ("slk_checker_decide", "一次，作为最后任务交接动作", "不让Codex/宿主代判")),
    ("incomplete-distinct", "slk-check-cell", ("INCOMPLETE", "不触发返工", "管理消息attempt不是原候选attempt")),
    ("unlimited-default", "slk-check-cell", ("aggregatebudget/timeout为原生0", "Owner冻结的有限预算不静默改写")),
    ("no-implicit-verdict", "slk-check-cell", ("零finding", "都不自动生成结论", "未实测目标环境不冒称实测")),
    ("own-facts", "slk-record-run", ("各写各的事实", "Worker", "Checker", "Supervisor", "OW")),
    ("retain-history", "slk-record-run", ("失败、返工、豁免", "追加保留", "导出失败只warning")),
    ("small-index-not-logs", "slk-record-run", ("紧凑evidenceindex", "不复制大日志/全部令牌历史", "原文读取无任意长度上限")),
    ("bound-first-rework", "slk-rework-cell", ("REWORK_REQUESTED", "D1_REWORK_DIRECTIVE", "candidateSHA-256", "下一合法round")),
    ("direct-worker-exception", "slk-rework-cell", ("直接交同一Worker", "唯一合法例外", "不是普通派工")),
    ("second-fail-split", "slk-rework-cell", ("第二次连续正式FAIL", "停止普通返工", "不发第三次普通重试")),
    ("rework-quality-target", "slk-rework-cell", ("绝大部分CELL首轮D1PASS", "不是通过率配额", "不影响Checker的真实判断")),
    ("product-fails-only", "slk-rework-cell", ("D0草稿自修", "INCOMPLETE不计连续产品FAIL", "不覆盖失败历史")),
    ("adjust-authority", "slk-adjust-run", ("AGGRESSIVE", "只有Owner改目标", "不代Worker施工或CheckerD1")),
    ("waiver-not-pass", "slk-adjust-run", ("豁免不是D1PASS", "也不是D2", "通过数与豁免数")),
    ("adjust-via-checker", "slk-adjust-run", ("revise-plan", "新revisionRoleHost", "Supervisor→Checker", "不得直接发Worker")),
    ("exact-recovery", "slk-recover-communication", ("已有精确投递异常", "匹配slk.native-start/v2", "不再发送/激活")),
    ("one-exact-retry", "slk-recover-communication", ("证明原投递无启动且目标空闲", "retry-exact原样一次", "consume-desktop-readback")),
    ("conditional-bridge", "slk-recover-communication", ("DESKTOP_BRIDGE_REQUIRED", "真实hostreceipt", "不争activewriter")),
    ("windows-invocation", "slk-recover-communication", ("python<slk-transport.pyz>", "--attempt-root是attempts根")),
    ("retired-format-recovery", "slk-recover-communication", ("旧格式/pre-D0/partial/context/terminal自动消费退役", "不为模板重跑Agent")),
    ("unique-parent-ow", "slk-overwatch-run", ("唯一直属OWsubagent", "不跨Supervisor共用", "每Run")),
    ("active-ow", "slk-overwatch-run", ("每600秒巡查", "持续循环", "不空final退出", "不由Temporal叫醒")),
    ("truth-crosscheck", "slk-overwatch-run", ("不可变终态", "缺WORK_STARTED也不能单独证明", "UNKNOWN报告")),
    ("report-continue", "slk-overwatch-run", ("先记自己的观察", "随后继续观察", "不等回复")),
    ("accepted-not-takeover", "slk-overwatch-run", ("accepted只证明受理", "不证明已读/接管/修复", "不套工程ACK/TOKEN")),
    ("confirmed-stop", "slk-overwatch-run", ("二次确认停止", "UNKNOWN不等于退出", "不强制重启")),
    ("guard-scope", "slk-overwatch-run", ("不派下一CELL", "保留现有成果", "Supervisor修复")),
    ("shared-temporal", "slk-manage-temporal", ("一套本地共享headless服务", "每Run独立SLK.Start/SLK.Run", "不裁决工程")),
    ("actual-admission", "slk-manage-temporal", ("AWAITING_ADMISSION拒绝所有派工", "真实READY/IDLE", "不要求cadence/cycle/首CELL")),
    ("sole-launcher", "slk-manage-temporal", ("Activity唯一物理启动", "Host不同时直发", "已有HostACK只补commit")),
    ("separate-timers", "slk-manage-temporal", ("1800秒", "直接通知", "1200秒", "不依赖OW")),
    ("real-workflow-health", "slk-manage-temporal", ("RUNNING且无closetime", "query可读或旧receipt不证明运行")),
    ("request-not-pause", "slk-pause-run", ("RUN_PAUSE_REQUESTED", "全部旧原生调用/writer", "不能改参数或称已暂停")),
    ("pause-census", "slk-pause-run", ("OCRVexecutor", "两个attemptroots", "不猜PID")),
    ("pause-suffix", "slk-pause-run", ("半提交重试原请求", "不换identity/revision", "TemporalRESUMED", "最后中央RUN_RESUMED")),
    ("confirmed-paused-time", "slk-pause-run", ("已确认PAUSED", "REQUESTED不扣", "重复resume不再扣", "其他Run计时继续")),
    ("combined-d2", "slk-close-run", ("真实组合", "D1PASS不作为D2通过证明", "形成初步D2判断后再读详细")),
    ("actual-d2-start", "slk-close-run", ("实际开始时", "start-d2", "D2_STARTED", "不在完成时补造开始")),
    ("terminal-order", "slk-close-run", ("D2_PASSED→terminalsnapshot→OWfinalcycle→close-overwatcher→RUN_CLOSED→close-role",)),
    ("terminal-census", "slk-close-run", ("当前revision", "inspect-run-quiescence", "UNKNOWN不当作停止")),
    ("own-pair-close", "slk-close-run", ("SLK.Run/SLK.Start", "COMPLETED与closetime", "保留共享Temporal")),
    ("owner-conclusion", "slk-close-run", ("完成与未完成收尾", "根记录路径", "不伪造D2PASS")),
]

def normalized(text):
    return re.sub(r"\s+", "", text.replace(chr(96), "").replace("**", ""))


@pytest.mark.parametrize("topic,owner,patterns", POLICIES, ids=[row[0] for row in POLICIES])
def test_policy_is_reachable_at_its_owner(topic, owner, patterns):
    source = normalized(read_skill(owner))
    for pattern in patterns:
        assert re.search(pattern, source), (topic, owner, pattern)


def test_collection_identity_and_inventory():
    assert re.fullmatch(r"\d+\.\d+\.\d+", read_version())
    assert set(EXPECTED_SKILLS) == {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    assert len(EXPECTED_SKILLS) == len(set(EXPECTED_SKILLS))
    for name in EXPECTED_SKILLS:
        assert_skill_shape(name)


def test_main_routes_to_every_child_once():
    main = read_skill("small-loop-skill")
    for name in EXPECTED_CHILDREN:
        assert main.count(chr(96) + "$" + name + chr(96)) == 1, name


def test_every_child_has_an_explicit_slk_usage_boundary():
    for name in EXPECTED_CHILDREN:
        source = read_skill(name)
        assert "SLK" in source and "Run" in source
        assert "仅用于" in source or "使用边界" in source, name


def test_internal_skill_routes_resolve():
    for name in EXPECTED_SKILLS:
        for source in (ROOT / "skills" / name).rglob("*.md"):
            for target in re.findall(r"\$((?:slk-|small-loop-skill)[a-z-]*)", source.read_text(encoding="utf-8")):
                assert target in EXPECTED_SKILLS, (source, target)


def test_resource_guard_precedes_models_and_team():
    plan = read_skill("slk-plan-run")
    assert plan.index("$slk-guard-resources") < plan.index("$slk-select-models")
    assert plan.index("Owner 确认方案及 Supervisor 人选") < plan.index("$slk-manage-team")


def test_conditional_operations_have_reachable_sources():
    sources = {
        "slk-manage-team": ("references/credential-preparation.md", ("DPAPI", "authenticate-role", "不自动轮换")),
        "slk-adjust-run": ("references/adjustment-operations.md", ("RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION", "reconcile-run-identities", "adopt-method-contract")),
        "slk-overwatch-run": ("references/cycle-evidence.md", ("slk.overwatch-scope-inspection/v1", "NOT_APPLICABLE", "SNAPSHOT_STALE")),
        "slk-pause-run": ("references/lifecycle-proof.md", ("coordinator_started_path", "pause_request_sha256", "slk.run-quiescence/v1")),
        "slk-close-run": ("references/close-operations.md", ("source_attempt_path", "close_binding_sha256", "lease", "D2_READY")),
        "slk-manage-temporal": ("references/admission.md", ("slk.subagent-overwatcher-proof/v1", "preflight-conformance-sample", "admission_kind")),
    }
    for name, (relative, required) in sources.items():
        assert relative in read_skill(name)
        text = read_skill(name) + (ROOT / "skills" / name / relative).read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, (name, marker)


def test_legacy_topology_and_retired_models_are_not_reintroduced():
    for name in EXPECTED_SKILLS:
        source = read_skill(name)
        for obsolete in ("GO → Chain", "GO→Chain", "GO -> Chain", "Worker → Supervisor → Checker"):
            assert obsolete not in source, (name, obsolete)
    assert "deepseek-v4-pro" not in read_skill("slk-select-models").lower()
    assert not (ROOT / "SKILL.md").exists()
