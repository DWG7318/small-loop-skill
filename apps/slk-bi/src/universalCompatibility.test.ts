import { describe, expect, it } from "vitest";
import { runFixture, twoRunFixture } from "./test/fixtures";
import { buildRunStripView, visibleRunSummaries, archivedRunSummaries, formatCellProgress } from "./runPresentation";
import { parseRunProjection } from "./contracts";
import { MESSAGE_CATALOG } from "./messages/catalog";
import { projectSupportedAuthoritativeMessages } from "./messages/messageFeed";
import { isArchivedRun } from "./webbi/worker";
import { parseUploadEnvelope } from "./webbi/contracts";
import { buildUploadEnvelope } from "./webbi/sync";

describe("universal BI source boundary", () => {
  it.each([false, true])("keeps missing progress unknown, including mixed cell states (%s)", (mixed) => {
    const run = structuredClone(runFixture);
    run.source_record = {kind: "markdown", creator_supervisor_id: "creator-a", revision: "r", status_text: "施工中", timing_available: false, progress: null};
    run.go_nodes = [run.go_nodes[0]!];
    const cell = run.go_nodes[0]!.cell_nodes[0]!;
    run.go_nodes[0]!.cell_nodes = [{...cell, cell_id: "one", state: mixed ? "d1_passed" : "unknown"}, {...cell, cell_id: "two", state: "unknown"}];
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    expect(view.progressAvailable).toBe(false);
    expect(formatCellProgress(view)).toBe("—/2 CELL");
  });
  it("can count progress from fully explicit cell states without a summary counter", () => {
    const run = structuredClone(runFixture);
    run.source_record = {kind: "markdown", creator_supervisor_id: "creator-a", revision: "r", status_text: "施工中", timing_available: false, progress: null};
    run.go_nodes = [run.go_nodes[0]!];
    const cell = run.go_nodes[0]!.cell_nodes[0]!;
    run.go_nodes[0]!.cell_nodes = [{...cell, cell_id: "one", state: "d1_passed"}, {...cell, cell_id: "two", state: "working"}];
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    expect(view.progressAvailable).toBe(true);
    expect(formatCellProgress(view)).toBe("1/2 CELL");
  });
  it("displays supplied legacy facts without inventing OW, events or elapsed work", () => {
    const run = structuredClone(runFixture);
    run.summary.slk_version = "3.0.9";
    run.events = []; run.token_history = [];
    run.source_record = {kind: "markdown", creator_supervisor_id: "creator-a", revision: "revision-a", status_text: "Worker 工作中", timing_available: false, progress: {passed: 2, total: 22}};
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, parseRunProjection(run), new Date());
    expect(view.slkVersion).toBe("3.0.9");
    expect(view.progress).toEqual({passed: 2, total: 22});
    expect(view.timingAvailable).toBe(false);
    expect(view.status).toBe("记录：Worker 工作中");
    expect(view.overwatcher).toBeNull();
    expect(projectSupportedAuthoritativeMessages(run, MESSAGE_CATALOG)).toEqual([]);
    const upload = buildUploadEnvelope({
      metadata: {schema_version: "slk.bi.metadata/v1", bi_version: "1.1.4", device_id: "pc-a", device_name: "PC A", webbi_sync_enabled: true},
      projects: twoRunFixture.projects, runs: {schema_version: "slk.bi.runs/v1", runs: [run.summary]}, runDetails: [run],
    }, "upload-test", "2026-10-16T00:00:00Z");
    const received = parseUploadEnvelope(upload, MESSAGE_CATALOG);
    expect(received.runs[0]?.run).toEqual(run);
    expect(received.runs[0]?.messages).toEqual([]);
  });
  it("keeps a closed Markdown run visible until the creator archives its information", () => {
    const run = structuredClone(runFixture);
    run.summary.archive_control = "creator";
    run.summary.closure_state = "closed";
    run.summary.archived_at = null;
    expect(visibleRunSummaries([run.summary])).toHaveLength(1);
    expect(archivedRunSummaries([run.summary])).toHaveLength(0);
    expect(isArchivedRun(run)).toBe(false);
    run.summary.archived_at = "2026-10-16T00:00:00Z";
    expect(visibleRunSummaries([run.summary])).toHaveLength(0);
    expect(isArchivedRun(run)).toBe(true);
  });
});
