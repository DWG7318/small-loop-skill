import { describe, expect, it } from "vitest";

import type { EventProjection, RunSummary } from "./contracts";
import { archivedRunSummaries, buildRunStripView, visibleRunSummaries } from "./runPresentation";
import { runFixture } from "./test/fixtures";

describe("compact Run presentation", () => {
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
