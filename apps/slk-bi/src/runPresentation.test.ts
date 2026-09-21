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
    expect(view.status).toBe("等待 D2");
    expect(view.slkVersion).toBe("4.1.0");
    expect(view.cells).toHaveLength(2);
    expect(view.source).toEqual({ kind: "solo", label: "独立" });
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
});
