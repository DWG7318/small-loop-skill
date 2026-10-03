import type { MessageCatalogEntry, MessageSourceKind, SlkRole } from "./messageFeed";

type CatalogSeed = readonly [messageType: string, labelZh: string, roles: readonly SlkRole[]];

const SUPERVISOR: readonly SlkRole[] = ["supervisor"];
const CHECKER: readonly SlkRole[] = ["checker"];
const WORKER: readonly SlkRole[] = ["worker"];
const OVERWATCHER: readonly SlkRole[] = ["overwatcher"];
const TECHNICAL: readonly SlkRole[] = ["supervisor", "checker", "worker"];
const ALL: readonly SlkRole[] = ["supervisor", "checker", "worker", "overwatcher"];

const EVENT_SEEDS: readonly CatalogSeed[] = [
  ["RUN_INITIALIZED", "Run 已建立", SUPERVISOR],
  ["OVERWATCHER_BOUND", "Overwatcher 已绑定", SUPERVISOR],
  ["PLAN_REVISED", "计划已修订", SUPERVISOR],
  ["ROLE_REGISTERED", "角色已登记", ["supervisor", "checker"]],
  ["ROLE_REPLACED", "角色已替换", ["supervisor", "checker"]],
  ["MODEL_CHANGED", "模型绑定已变更", SUPERVISOR],
  ["SESSION_REBOUND", "Session 已重新绑定", SUPERVISOR],
  ["OVERWATCHER_TURN_RESUMED", "Overwatcher turn 已恢复", SUPERVISOR],
  ["EXEMPTION_GRANTED", "豁免已批准", SUPERVISOR],
  ["D2_STARTED", "D2 已开始", SUPERVISOR],
  ["D2_PASSED", "D2 已通过", SUPERVISOR],
  ["D2_FAILED", "D2 未通过", SUPERVISOR],
  ["RUN_SUPERSEDED", "Run 已被替代", SUPERVISOR],
  ["RUN_ABANDONED", "Run 已废除", SUPERVISOR],
  ["RUN_CLOSED", "Run 已关闭", SUPERVISOR],
  ["CELL_DISPATCHED", "CELL 已派发", CHECKER],
  ["D1_STARTED", "D1 已开始", CHECKER],
  ["D1_INCOMPLETE", "D1 信息不完整", CHECKER],
  ["D1_PASSED", "D1 已通过", CHECKER],
  ["D1_FAILED", "D1 未通过", CHECKER],
  ["REWORK_REQUESTED", "返工已要求", SUPERVISOR],
  ["CELL_SPLIT", "CELL 已拆分", CHECKER],
  ["CANDIDATE_FORWARDED", "候选已转交", CHECKER],
  ["WORK_STARTED", "Worker 开始工作", WORKER],
  ["WORK_PROGRESS", "Worker 记录进展", WORKER],
  ["BLOCKER_REPORTED", "Worker 报告阻断", WORKER],
  ["CHANGE_RECORDED", "变更已记录", WORKER],
  ["D0_COMPLETED", "D0 已完成", WORKER],
  ["CANDIDATE_SUBMITTED", "候选已交付", WORKER],
  ["RESOURCE_CONTENDED", "资源发生冲突", TECHNICAL],
  ["RESOURCE_RECOVERED", "资源已恢复", TECHNICAL],
  ["EVIDENCE_REGISTERED", "证据已登记", ALL],
  ["TOKEN_HANDED_OFF", "SLK TOKEN 已交接", TECHNICAL],
  ["TRANSPORT_FAILED", "消息投递失败", TECHNICAL],
  ["TRANSPORT_STARTED", "接收方原生工作已启动", TECHNICAL],
];

const OBSERVATION_SEEDS: readonly CatalogSeed[] = [
  ["DELIVERY_UNCONFIRMED", "投递未确认", OVERWATCHER],
  ["DELIVERY_RETRYING", "投递正在重试", OVERWATCHER],
  ["ACTIVITY_UNPROVEN", "活动无法证实", OVERWATCHER],
  ["RECORD_CONFLICT", "记录与事实冲突", OVERWATCHER],
  ["RECOVERY_ESCALATED", "恢复已升级", OVERWATCHER],
  ["PROJECTION_REFRESH_REQUESTED", "投影刷新已请求", OVERWATCHER],
  ["OVERWATCHER_CLOSED", "Overwatcher 已关闭", OVERWATCHER],
  ["WORKER_COMPLETION_HANDOFF_MISSING", "Worker 完成交接缺失", OVERWATCHER],
];

function entries(sourceKind: MessageSourceKind, seeds: readonly CatalogSeed[]) {
  return seeds.map<MessageCatalogEntry>(([message_type, label_zh, allowed_roles]) => ({
    source_kind: sourceKind,
    message_type,
    label_zh,
    allowed_roles: [...allowed_roles],
    notification_eligible: true,
  }));
}

export const MESSAGE_CATALOG: readonly MessageCatalogEntry[] = Object.freeze([
  ...entries("EVENT", EVENT_SEEDS),
  ...entries("OW_OBSERVATION", OBSERVATION_SEEDS),
]);

export function catalogKey(sourceKind: MessageSourceKind, messageType: string) {
  return `${sourceKind}:${messageType}`;
}

export function catalogEntry(
  catalog: readonly MessageCatalogEntry[],
  sourceKind: MessageSourceKind,
  messageType: string,
) {
  return catalog.find(
    (entry) => entry.source_kind === sourceKind && entry.message_type === messageType,
  );
}
