import { describe, expect, it } from "vitest";

import type { EventProjection, RunSummary, RunView } from "./contracts";
import { archivedRunSummaries, buildRunStripView, visibleRunSummaries } from "./runPresentation";
import { runFixture } from "./test/fixtures";

function splitHistoryRun(): RunView {
  const split = new Set(["CELL02", "CELL02-A", "CELL02-A3", "CELL03"]);
  const passed = new Set(["CELL01", "CELL02-A1", "CELL02-A2", "CELL02-A3A", "CELL02-A3B", "CELL02-B"]);
  const ids = ["CELL01", "CELL02", "CELL02-A", "CELL02-A1", "CELL02-A2", "CELL02-A3", "CELL02-A3A", "CELL02-A3B", "CELL02-B", "CELL03", "CELL03-A", "CELL03-B", "CELL04", "CELL05", "CELL06", "CELL07"];
  return {
    ...runFixture,
    summary: { ...runFixture.summary, current_plan_revision: 5 },
    go_nodes: [{
      ...runFixture.go_nodes[0]!,
      cell_nodes: ids.map((cell_id, index) => ({
        ...runFixture.go_nodes[0]!.cell_nodes[0]!, cell_id, ordinal: index + 1, title: cell_id,
        state: split.has(cell_id) ? "split" : passed.has(cell_id) ? "d1_passed" : "planned",
      })),
    }],
  };
}

describe("compact Run presentation", () => {
  const project = { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 };

  it("excludes only confirmed pause time and resumes the same open work interval", () => {
    const fact = (event_type: string, minutes: number): EventProjection => ({
      event_id: event_type, event_type, author_role_instance_id: "worker-a", go_id: "GO-001",
      cell_id: "CELL-001", attempt: 1, details_json: "{}", corrects_event_id: null,
      occurred_at: new Date(Date.parse("2026-09-20T00:00:00Z") + minutes * 60_000).toISOString(),
    });
    const run = { ...runFixture, events: [fact("WORK_STARTED", 0), fact("RUN_PAUSE_REQUESTED", 10),
      fact("RUN_PAUSED", 20), fact("RUN_RESUMED", 80), fact("CANDIDATE_SUBMITTED", 90)] };
    expect(buildRunStripView(project, run, new Date("2026-09-20T02:00:00Z")).totalWorkMs).toBe(30 * 60_000);
  });

  it("ends D1 elapsed work at the Checker's INCOMPLETE fact before TOKEN handoff", () => {
    const event = (event_type: string, minute: number): EventProjection => ({
      event_id: event_type, event_type, author_role_instance_id: "checker-a", go_id: "GO-001",
      cell_id: "CELL-001", attempt: 1, details_json: "{}", corrects_event_id: null,
      occurred_at: `2026-09-20T00:${String(minute).padStart(2, "0")}:00Z`,
    });
    const run = { ...runFixture, events: [event("D1_STARTED", 0), event("D1_INCOMPLETE", 20)],
      roles: runFixture.roles.map((role) => ({ ...role, display_state: "waiting" })) };
    expect(buildRunStripView(project, run, new Date("2026-09-20T01:00:00Z")).totalWorkMs).toBe(20 * 60_000);
  });

  it("counts only effective CELLs while preserving every split history record", () => {
    const run = splitHistoryRun();
    const before = JSON.stringify(run);
    const view = buildRunStripView(project, run, new Date("2026-09-20T02:00:00Z"));

    expect(view.progress).toEqual({ passed: 6, total: 12 });
    expect(view.cells).toHaveLength(16);
    for (const id of ["CELL02", "CELL02-A", "CELL02-A3", "CELL03"]) {
      const history = view.cells.find((cell) => cell.name === id)!;
      expect(history.meta).toContain("已拆分");
      expect(history.tone).toBe("exempt");
    }
    expect(JSON.stringify(run)).toBe(before);
  });

  it("does not let split parents prevent the effective CELLs from waiting for D2", () => {
    const run = splitHistoryRun();
    run.go_nodes[0]!.cell_nodes = run.go_nodes[0]!.cell_nodes.map((cell) =>
      cell.state === "split" ? cell : { ...cell, state: "d1_passed" });
    run.events = [{ ...runFixture.events[0]!, event_type: "D1_PASSED" }];
    const view = buildRunStripView(project, run, new Date("2026-09-20T02:00:00Z"));

    expect(view.status).toBe("等待 D2");
    expect(view.progress).toEqual({ passed: 12, total: 12 });
    expect(view.cells).toHaveLength(16);
  });

  it("does not select a split parent as the fallback current CELL", () => {
    const run = splitHistoryRun();
    run.token_history = [];
    run.roles = run.roles.map((role) => ({ ...role, current_cell_id: null }));
    expect(buildRunStripView(project, run, new Date()).currentCellId).toBe("CELL03-A");
  });

  it("keeps archived Runs out of the primary surface", () => {
    const current = runFixture.summary;
    const archived: RunSummary = {
      ...current,
      run_id: "run-old",
      state: "archived",
      closure_state: "superseded",
      archive_reason: "superseded",
      archived_at: "2026-09-20T00:30:00Z",
      superseded_by_run_id: current.run_id,
    };

    expect(visibleRunSummaries([archived, current]).map((run) => run.run_id)).toEqual([
      "run-a",
    ]);
    expect(archivedRunSummaries([archived, current]).map((run) => run.run_id)).toEqual([
      "run-old",
    ]);
  });

  it("keeps explicit successor history out of the current surface", () => {
    const current: RunSummary = {
      ...runFixture.summary,
      run_id: "run-current",
      predecessor_run_id: "run-old",
      lineage_root_run_id: "run-old",
      identity_state: "CURRENT",
    };
    const history: RunSummary = {
      ...runFixture.summary,
      run_id: "run-old",
      state: "archived",
      closure_state: "superseded",
      archived_at: "2026-09-20T00:30:00Z",
      superseded_by_run_id: "run-current",
      predecessor_run_id: null,
      lineage_root_run_id: "run-old",
      identity_state: "HISTORY",
    };

    expect(visibleRunSummaries([history, current]).map((run) => run.run_id)).toEqual([
      "run-current",
    ]);
  });

  it("derives concise identity, progress, responsibility, and waiting-free durations", () => {
    const events: EventProjection[] = [
      {
        event_id: "worker-start",
        event_type: "WORK_STARTED",
        author_role_instance_id: "worker-a",
        go_id: "GO-001",
        cell_id: "CELL-001",
        attempt: 1,
        details_json: "{}",
        corrects_event_id: null,
        occurred_at: "2026-09-20T00:00:00Z",
      },
      {
        event_id: "candidate",
        event_type: "CANDIDATE_SUBMITTED",
        author_role_instance_id: "worker-a",
        go_id: "GO-001",
        cell_id: "CELL-001",
        attempt: 1,
        details_json: "{}",
        corrects_event_id: null,
        occurred_at: "2026-09-20T00:20:00Z",
      },
      {
        event_id: "d1-start",
        event_type: "D1_STARTED",
        author_role_instance_id: "checker-a",
        go_id: "GO-001",
        cell_id: "CELL-001",
        attempt: 1,
        details_json: "{}",
        corrects_event_id: null,
        occurred_at: "2026-09-20T01:00:00Z",
      },
      {
        event_id: "d1-pass",
        event_type: "D1_PASSED",
        author_role_instance_id: "checker-a",
        go_id: "GO-001",
        cell_id: "CELL-001",
        attempt: 1,
        details_json: "{}",
        corrects_event_id: null,
        occurred_at: "2026-09-20T01:17:00Z",
      },
    ];
    const run = {
      ...runFixture,
      events,
      go_nodes: [
        {
          ...runFixture.go_nodes[0]!,
          cell_nodes: [
            { ...runFixture.go_nodes[0]!.cell_nodes[0]!, state: "d1_passed" },
            {
              ...runFixture.go_nodes[0]!.cell_nodes[0]!,
              cell_id: "CELL-002",
              ordinal: 2,
              title: "Next cell",
              state: "planned",
            },
          ],
        },
      ],
    };

    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 },
      run,
      new Date("2026-09-20T02:00:00Z"),
    );

    expect(view.runName).toBe("Close flow");
    expect(view.startDate).toBe("09-20");
    expect(view.progress).toEqual({ passed: 1, total: 2 });
    expect(view.totalWorkMs).toBe(37 * 60_000);
    expect(view.currentCellWorkMs).toBe(37 * 60_000);
    expect(view.status).toBe("等待下一 CELL");
    expect(view.slkVersion).toBe("4.1.0");
    expect(view.cells).toHaveLength(2);
    expect(view.source).toEqual({ kind: "solo", label: "独立" });
  });

  it("waits for D2 only after every CELL has passed D1", () => {
    const run = {
      ...runFixture,
      go_nodes: [
        {
          ...runFixture.go_nodes[0]!,
          cell_nodes: [
            { ...runFixture.go_nodes[0]!.cell_nodes[0]!, state: "d1_passed" },
          ],
        },
      ],
      events: [
        {
          ...runFixture.events[0]!,
          event_id: "d1-pass",
          event_type: "D1_PASSED",
          author_role_instance_id: "checker-a",
        },
      ],
    };

    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 },
      run,
      new Date("2026-09-20T02:00:00Z"),
    );

    expect(view.status).toBe("等待 D2");
  });

  it("shows identity conflicts instead of silently merging unrelated cards", () => {
    const duplicate = {
      ...runFixture,
      summary: { ...runFixture.summary, identity_state: "DUPLICATE_ACTIVE_RUN" as const },
    };
    const orphaned = {
      ...runFixture,
      summary: { ...runFixture.summary, identity_state: "ORPHANED_IDENTITY" as const },
    };
    const project = { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 2 };

    expect(buildRunStripView(project, duplicate, new Date()).status).toBe("Run 身份冲突");
    expect(buildRunStripView(project, orphaned, new Date()).status).toBe("Run 身份待确认");
  });

  it("uses accepted Overwatcher evidence to reject stale activity without changing progress", () => {
    const run = {
      ...runFixture,
      operational_observations: [
        {
          observation_id: "observation-a",
          overwatcher_role_instance_id: "overwatcher-a",
          go_id: "GO-001",
          cell_id: "CELL-001",
          attempt: 1,
          plan_revision: 1,
          kind: "ACTIVITY_UNPROVEN",
          related_event_id: "work-started",
          message_id: null,
          evidence_refs_json: '["native-snapshot.json"]',
          details_json: "{}",
          occurred_at: "2026-09-20T00:10:00Z",
        },
      ],
    };

    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 },
      run,
      new Date("2026-09-20T02:00:00Z"),
    );

    expect(view.status).toBe("活动无法证明");
    expect(view.progress).toEqual({ passed: 0, total: 1 });
  });

  it("shows an unresolved Overwatcher incident without claiming the observer paused", () => {
    const run = {
      ...runFixture,
      overwatcher_incident_transitions: [
        {
          transition_id: "incident-transition-1",
          incident_id: "incident-1",
          binding_revision: 1,
          incident_code: "OVERWATCHER_CONTINUITY_VIOLATION",
          state: "OPEN",
          evidence_path: "evidence/incident.json",
          evidence_sha256: "b".repeat(64),
          occurred_at: "2026-09-20T00:10:00Z",
        },
      ],
    };

    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 },
      run,
      new Date("2026-09-20T00:11:00Z"),
    );

    expect(view.overwatcher?.label).toBe("异常待处理");
    expect(view.overwatcher?.tone).toBe("blocked");
    expect(view.progress).toEqual({ passed: 0, total: 1 });
  });

  it.each([
    ["RUN_PAUSE_REQUESTED", "暂停请求中"],
    ["RUN_PAUSED", "已暂停"],
    ["RUN_RESUMED", "已恢复"],
    ["D2_PASSED", "验收通过 · 待收尾"],
    ["D1_FAILED", "等待 Supervisor 指引"],
    ["REWORK_REQUESTED", "Worker 返工中"],
  ])("projects %s facts even after role registration", (event_type, expected) => {
    const run: RunView = {
      ...runFixture,
      events: [
        ...runFixture.events,
        { ...runFixture.events[0]!, event_id: "fact", event_type, occurred_at: "2026-09-20T00:01:00Z" },
        { ...runFixture.events[0]!, event_id: "role", event_type: "ROLE_REGISTERED", occurred_at: "2026-09-20T00:02:00Z" },
      ],
    };
    const view = buildRunStripView(project, run, new Date("2026-09-20T00:03:00Z"));
    expect(view.status).toBe(expected);
    if (event_type === "D1_FAILED") expect(view.cells[0]!.meta).toContain("等待 Supervisor 指引");
  });

  it.each(["D1_INCOMPLETE", "D0_COMPLETED"])("keeps %s phase-ending facts through TOKEN handoff and role registration", (event_type) => {
    const event = runFixture.events[0]!;
    const run: RunView = { ...runFixture,
      token_history: [{ ...runFixture.token_history[0]!, to_role_instance_id: "supervisor-a" }],
      events: [
        { ...event, event_id: "inspection", event_type: "D1_STARTED", occurred_at: "2026-09-20T00:01:00Z" },
        { ...event, event_id: "phase-ended", event_type, occurred_at: "2026-09-20T00:02:00Z" },
        { ...event, event_id: "token", event_type: "TOKEN_HANDED_OFF", occurred_at: "2026-09-20T00:03:00Z" },
        { ...event, event_id: "register", event_type: "ROLE_REGISTERED", occurred_at: "2026-09-20T00:04:00Z" },
      ],
    };
    const before = JSON.stringify(run);
    const view = buildRunStripView(project, run, new Date("2026-09-20T00:05:00Z"));
    expect(view.status).toBe("等待 Supervisor");
    expect(view.statusTone).toBe("wait");
    expect(view.cells[0]!.tone).toBe("wait");
    expect(view.cells[0]!.meta).not.toContain("进行中");
    expect(JSON.stringify(run)).toBe(before);
  });

  it("holds a formal pause until a formal resume, then projects subsequent work normally", () => {
    const events = ["RUN_PAUSE_REQUESTED", "RUN_PAUSED", "WORK_PROGRESS", "RUN_RESUMED", "WORK_STARTED"]
      .map((event_type, index) => ({ ...runFixture.events[0]!, event_id: String(index), event_type,
        occurred_at: `2026-09-20T00:0${index + 1}:00Z` }));
    expect(buildRunStripView(project, { ...runFixture, events: events.slice(0, 3) }, new Date()).status).toBe("已暂停");
    expect(buildRunStripView(project, { ...runFixture, events: events.slice(0, 4) }, new Date()).status).toBe("已恢复");
    expect(buildRunStripView(project, { ...runFixture, events }, new Date()).status).toBe("Worker 工作中");
    expect(buildRunStripView(project, { ...runFixture, summary: { ...runFixture.summary, closure_state: "closed" }, events }, new Date()).status).toBe("已完成");
  });

  it("shows a terminally closed Overwatcher separately from engineering completion", () => {
    const run = {
      ...runFixture,
      overwatcher_binding_transitions: [
        {
          transition_id: "binding-close-1",
          binding_revision: 1,
          transition_type: "TERMINAL_CLOSE",
          cycle_id: "cycle-final",
          runtime_revision: 9,
          evidence_ref: "evidence/close.json",
          occurred_at: "2026-09-20T01:00:00Z",
        },
      ],
    };

    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 1 },
      run,
      new Date("2026-09-20T01:01:00Z"),
    );

    expect(view.overwatcher?.label).toBe("已关闭");
    expect(view.overwatcher?.detail).toContain("绑定 TERMINAL_CLOSE");
    expect(view.status).toBe("Worker 工作中");
  });

  it("uses a stable group key for SLKs in the same CLK or GLK project", () => {
    const run = {
      ...runFixture,
      summary: {
        ...runFixture.summary,
        source_kind: "glk" as const,
        source_project_name: "Platform 全系统重构",
      },
    };
    const view = buildRunStripView(
      { project_id: "project-a", name: "LCaS", repository_url: null, last_known_path: "D:/LCaS", run_count: 2 },
      run,
      new Date(),
    );

    expect(view.source).toEqual({ kind: "glk", label: "GLK · Platform 全系统重构" });
    expect(view.sourceGroupKey).toBe("glk:Platform 全系统重构");
  });

  it("uses the immutable project identity to color independent projects", () => {
    const firstProject = {
      project_id: "project-a",
      name: "LCaS",
      repository_url: null,
      last_known_path: "D:/LCaS",
      run_count: 1,
    };
    const secondProject = { ...firstProject, project_id: "project-b", name: "WXGate" };

    const first = buildRunStripView(firstProject, runFixture, new Date());
    const repeated = buildRunStripView(firstProject, runFixture, new Date());
    const second = buildRunStripView(
      secondProject,
      { ...runFixture, summary: { ...runFixture.summary, project_id: "project-b" } },
      new Date(),
    );

    expect(first.sourceGroupKey).toBe("project:project-a");
    expect(repeated.sourceGroupKey).toBe(first.sourceGroupKey);
    expect(second.sourceGroupKey).toBe("project:project-b");
  });
});
