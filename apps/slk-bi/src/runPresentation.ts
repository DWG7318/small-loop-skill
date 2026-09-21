import type {
  CellProjection,
  EventProjection,
  ProjectSummary,
  RoleProjection,
  RunSummary,
  RunView,
} from "./contracts";

export type RunTone = "done" | "active" | "wait" | "exempt" | "rework" | "blocked";

export interface RunStripRole {
  role: "Supervisor" | "Checker" | "Worker";
  agent: string;
  model: string;
  reasoning: string;
}

export interface RunStripCell {
  id: string;
  name: string;
  note: string;
  meta: string;
  tone: RunTone;
}

export interface RunStripView {
  runId: string;
  projectName: string;
  runName: string;
  description: string;
  startDate: string;
  progress: { passed: number; total: number };
  currentCellId: string | null;
  totalWorkMs: number;
  currentCellWorkMs: number;
  status: string;
  statusTone: RunTone;
  slkVersion: string;
  source: { kind: "solo" | "clk" | "glk"; label: string };
  sourceGroupKey: string;
  roles: RunStripRole[];
  cells: RunStripCell[];
}

interface Interval {
  start: number;
  end: number;
  cellId: string | null;
}

const ROLE_LABELS = {
  supervisor: "Supervisor",
  checker: "Checker",
  worker: "Worker",
} as const;

export function visibleRunSummaries(runs: RunSummary[]) {
  return runs.filter(
    (run) => run.closure_state === "open" && run.state !== "archived" && !run.archived_at,
  );
}

export function archivedRunSummaries(runs: RunSummary[]) {
  return runs.filter(
    (run) => run.closure_state !== "open" || run.state === "archived" || Boolean(run.archived_at),
  );
}

function effectiveEvents(events: EventProjection[]) {
  const corrected = new Set(
    events.map((event) => event.corrects_event_id).filter((id): id is string => Boolean(id)),
  );
  return [...events]
    .filter((event) => !corrected.has(event.event_id))
    .sort((left, right) => Date.parse(left.occurred_at) - Date.parse(right.occurred_at));
}

function workIntervals(run: RunView, now: Date): Interval[] {
  const open = new Map<string, { start: number; cellId: string | null; author: string }>();
  const intervals: Interval[] = [];
  const events = effectiveEvents(run.events);

  function key(phase: string, event: EventProjection) {
    return `${phase}:${event.author_role_instance_id}:${event.cell_id ?? "run"}:${event.attempt ?? 0}`;
  }

  function begin(phase: string, event: EventProjection) {
    const time = Date.parse(event.occurred_at);
    if (Number.isFinite(time)) {
      open.set(key(phase, event), {
        start: time,
        cellId: event.cell_id,
        author: event.author_role_instance_id,
      });
    }
  }

  function end(phase: string, event: EventProjection) {
    const intervalKey = key(phase, event);
    const started = open.get(intervalKey);
    const time = Date.parse(event.occurred_at);
    if (!started || !Number.isFinite(time) || time < started.start) return;
    intervals.push({ start: started.start, end: time, cellId: started.cellId });
    open.delete(intervalKey);
  }

  for (const event of events) {
    if (event.event_type === "WORK_STARTED" || event.event_type === "RESOURCE_RECOVERED") {
      begin("worker", event);
    } else if (
      event.event_type === "CANDIDATE_SUBMITTED" ||
      event.event_type === "BLOCKER_REPORTED" ||
      event.event_type === "RESOURCE_CONTENDED"
    ) {
      end("worker", event);
    } else if (event.event_type === "D1_STARTED") {
      begin("d1", event);
    } else if (event.event_type === "D1_PASSED" || event.event_type === "D1_FAILED") {
      end("d1", event);
    } else if (event.event_type === "D2_STARTED") {
      begin("d2", event);
    } else if (event.event_type === "D2_PASSED" || event.event_type === "D2_FAILED") {
      end("d2", event);
    }
  }

  for (const started of open.values()) {
    const role = run.roles.find(
      (candidate) =>
        candidate.role_instance_id === started.author &&
        candidate.lifecycle === "active" &&
        candidate.display_state === "working",
    );
    if (role && now.getTime() >= started.start) {
      intervals.push({ start: started.start, end: now.getTime(), cellId: started.cellId });
    }
  }
  return intervals;
}

function unionDuration(intervals: Interval[]) {
  const sorted = [...intervals]
    .filter((interval) => interval.end >= interval.start)
    .sort((left, right) => left.start - right.start);
  let total = 0;
  let start: number | undefined;
  let end: number | undefined;
  for (const interval of sorted) {
    if (start === undefined || end === undefined) {
      start = interval.start;
      end = interval.end;
    } else if (interval.start <= end) {
      end = Math.max(end, interval.end);
    } else {
      total += end - start;
      start = interval.start;
      end = interval.end;
    }
  }
  return total + (start === undefined || end === undefined ? 0 : end - start);
}

function cells(run: RunView) {
  return run.go_nodes.flatMap((legacyGroup) => legacyGroup.cell_nodes);
}

function currentCellId(run: RunView) {
  return (
    run.token_history.at(-1)?.cell_id ??
    run.roles.find((role) => role.lifecycle === "active" && role.current_cell_id)?.current_cell_id ??
    cells(run).find((cell) => cell.state !== "d1_passed")?.cell_id ??
    null
  );
}

function status(run: RunView, responsible?: RoleProjection): [string, RunTone] {
  if (run.summary.closure_state === "closed") return ["已完成", "done"];
  if (run.summary.closure_state === "abandoned") return ["已废弃", "exempt"];
  if (run.summary.closure_state === "superseded") return ["已替代", "exempt"];
  const event = effectiveEvents(run.events).at(-1)?.event_type;
  if (event === "WORK_STARTED" || event === "WORK_PROGRESS") return ["Worker 工作中", "active"];
  if (event === "CANDIDATE_SUBMITTED") return ["等待 Checker", "wait"];
  if (event === "D1_STARTED") return ["Checker 检验中", "active"];
  if (event === "D1_PASSED") return ["等待 D2", "wait"];
  if (event === "D1_FAILED" || event === "REWORK_REQUESTED") return ["Worker 返工中", "rework"];
  if (event === "D2_STARTED") return ["D2 检验中", "active"];
  if (event === "D2_PASSED" || event === "RUN_CLOSED") return ["已完成", "done"];
  if (
    event === "BLOCKER_REPORTED" ||
    event === "RESOURCE_CONTENDED" ||
    event === "TRANSPORT_FAILED"
  ) {
    return ["需要处理", "blocked"];
  }
  if (!responsible) return ["等待分配", "wait"];
  return [`等待 ${ROLE_LABELS[responsible.role]}`, "wait"];
}

function cellView(cell: CellProjection, run: RunView, intervals: Interval[]): RunStripCell {
  const events = effectiveEvents(run.events).filter((event) => event.cell_id === cell.cell_id);
  const latest = events.at(-1)?.event_type;
  let tone: RunTone = "wait";
  let state = "未开始";
  if (cell.state === "d1_passed" || latest === "D1_PASSED") {
    tone = "done";
    state = "已完成 · D1 PASS";
  } else if (latest === "D1_FAILED" || latest === "REWORK_REQUESTED") {
    tone = "rework";
    state = "返工中";
  } else if (latest === "BLOCKER_REPORTED" || latest === "RESOURCE_CONTENDED") {
    tone = "blocked";
    state = "需要处理";
  } else if (latest === "WORK_STARTED" || latest === "WORK_PROGRESS") {
    tone = "active";
    state = "进行中 · Worker";
  } else if (latest === "D1_STARTED") {
    tone = "active";
    state = "进行中 · Checker";
  } else if (latest === "CANDIDATE_SUBMITTED") {
    state = "等待 Checker";
  }
  const duration = unionDuration(intervals.filter((interval) => interval.cellId === cell.cell_id));
  const durationText = duration ? ` · ${formatDuration(duration)}` : "";
  const attemptText = cell.attempt > 1 ? ` · 第${cell.attempt}次施工` : "";
  const notePrefix = tone === "done" ? "结果" : tone === "active" || tone === "rework" ? "当前" : "目标";
  return {
    id: `CELL ${String(cell.ordinal).padStart(2, "0")}`,
    name: cell.title,
    note: `${notePrefix}：${cell.outcome || cell.objective}`,
    meta: `${state}${durationText}${attemptText}`,
    tone,
  };
}

function source(run: RunSummary) {
  const kind: "solo" | "clk" | "glk" =
    run.source_kind === "clk" || run.source_kind === "glk" ? run.source_kind : "solo";
  if (kind === "solo") {
    return { source: { kind, label: "独立" } as const, sourceGroupKey: "solo" };
  }
  const name = run.source_project_name?.trim() || "未命名项目";
  return {
    source: { kind, label: `${kind.toUpperCase()} · ${name}` } as const,
    sourceGroupKey: `${kind}:${name}`,
  };
}

export function buildRunStripView(project: ProjectSummary, run: RunView, now: Date): RunStripView {
  const allCells = cells(run);
  const passed = allCells.filter((cell) => cell.state === "d1_passed").length;
  const cellId = currentCellId(run);
  const intervals = workIntervals(run, now);
  const responsibleId = run.token_history.at(-1)?.to_role_instance_id;
  const responsible = run.roles.find((role) => role.role_instance_id === responsibleId);
  const roles = (["supervisor", "checker", "worker"] as const).map((roleName) => {
    const role = run.roles.find(
      (candidate) => candidate.role === roleName && candidate.lifecycle === "active",
    );
    return {
      role: ROLE_LABELS[roleName],
      agent: role?.agent_runtime ?? "未登记",
      model: role?.model ?? "未登记",
      reasoning: role?.reasoning ?? "",
    };
  });
  const start = new Date(run.summary.created_at);
  const startDate = Number.isNaN(start.getTime())
    ? "-- --"
    : `${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`;
  const [statusText, statusTone] = status(run, responsible);
  const sourceInfo = source(run.summary);

  return {
    runId: run.run_id,
    projectName: project.name,
    runName: run.summary.run_name || allCells[0]?.title || run.summary.goal,
    description: run.summary.run_description || run.summary.goal,
    startDate,
    progress: { passed, total: allCells.length },
    currentCellId: cellId,
    totalWorkMs: unionDuration(intervals),
    currentCellWorkMs: unionDuration(intervals.filter((interval) => interval.cellId === cellId)),
    status: statusText,
    statusTone,
    slkVersion: run.summary.slk_version,
    roles,
    cells: allCells.map((cell) => cellView(cell, run, intervals)),
    ...sourceInfo,
  };
}

export function formatDuration(milliseconds: number) {
  const minutes = Math.max(0, Math.floor(milliseconds / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h${remainder}m` : `${hours}h`;
}
