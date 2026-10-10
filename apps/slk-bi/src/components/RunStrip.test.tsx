import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { buildRunStripView, type RunStripView } from "../runPresentation";
import { runFixture, twoRunFixture } from "../test/fixtures";
import { groupTone, RunStrip } from "./RunStrip";

afterEach(cleanup);

function InteractiveStrip({ view }: { view: RunStripView }) {
  const [open, setOpen] = useState(false);
  return <RunStrip view={view} open={open} onToggle={() => setOpen(!open)} />;
}

describe("RunStrip", () => {
  it.each([[0, 8], [1, 8], [8, 8], [9, 16], [16, 16], [17, 24], [24, 24], [25, 24], [1000, 24]])(
    "shows %i effective CELLs in %i proportional segments without premature full progress", (total, segments) => {
      const view = buildRunStripView(twoRunFixture.projects.projects[0]!, runFixture, new Date());
      view.progress = { total, passed: Math.max(0, total - 1) };
      const { rerender } = render(<RunStrip view={view} />);
      const progress = screen.getByRole("progressbar");
      expect(progress.children).toHaveLength(segments);
      expect(progress).toHaveAttribute("aria-valuemax", String(total));
      expect(progress).toHaveAttribute("aria-valuenow", String(view.progress.passed));
      expect(progress).toHaveAttribute("title", expect.stringContaining("比例概览"));
      expect(progress.querySelectorAll(".segment-active").length).toBeLessThan(segments);
      rerender(<RunStrip view={{ ...view, progress: { total, passed: total } }} />);
      expect(progress.querySelectorAll(".segment-active")).toHaveLength(total ? segments : 0);
    },
  );

  it("reverses only a COPY of the execution list and keeps every CELL reachable", async () => {
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, runFixture, new Date());
    view.cells = Array.from({ length: 7 }, (_, index) => ({
      ...view.cells[0]!, cellId: `cell-${index}`, id: `CELL ${index % 3 + 1}`, name: `Execution ${index + 1}`,
    }));
    const before = JSON.stringify(view.cells);
    const user = userEvent.setup();
    render(<InteractiveStrip view={view} />);
    await user.click(screen.getByRole("button", { name: /展开 Close flow/ }));
    const list = screen.getByRole("list", { name: "Close flow CELL 记录" });
    expect(list).toHaveAttribute("tabindex", "0");
    expect(Array.from(list.querySelectorAll("strong")).map((item) => item.textContent))
      .toEqual(["Execution 7", "Execution 6", "Execution 5", "Execution 4", "Execution 3", "Execution 2", "Execution 1"]);
    expect(JSON.stringify(view.cells)).toBe(before);
  });

  it("keeps the original CELL DOM identity when later GO rows reuse a displayed ordinal", () => {
    const first = runFixture.go_nodes[0]!;
    const run = {
      ...runFixture,
      go_nodes: [first, { ...first, go_id: "GO-002", ordinal: 2, cell_nodes: [
        { ...first.cell_nodes[0]!, cell_id: "second-go-cell", title: "Second GO cell" },
      ] }],
    };
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    const { rerender } = render(<RunStrip view={view} open />);
    const originalRow = screen.getByText("Implement closure").closest("li");
    const extended = { ...run, go_nodes: [...run.go_nodes, { ...first, go_id: "GO-003", ordinal: 3,
      cell_nodes: [{ ...first.cell_nodes[0]!, cell_id: "third-go-cell", title: "Third GO cell" }],
    }] };
    rerender(<RunStrip view={buildRunStripView(twoRunFixture.projects.projects[0]!, extended, new Date())} open />);
    expect(screen.getByText("Implement closure").closest("li")).toBe(originalRow);
    expect(screen.getAllByText("CELL 01")).toHaveLength(3);
  });

  it("reverses the GO-then-CELL execution list, not CELL ordinals across GO groups", () => {
    const group = runFixture.go_nodes[0]!;
    const cell = group.cell_nodes[0]!;
    const run = { ...runFixture, token_history: [], roles: [], go_nodes: [
      { ...group, cell_nodes: [
        { ...cell, title: "First GO first" },
        { ...cell, cell_id: "go1-tail", ordinal: 9, title: "First GO tail" },
      ] },
      { ...group, go_id: "GO-002", ordinal: 2, cell_nodes: [
        { ...cell, cell_id: "go2-first", title: "Second GO first" },
        { ...cell, cell_id: "go2-tail", ordinal: 2, title: "Second GO tail" },
      ] },
    ] };
    const before = JSON.stringify(run);
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    render(<RunStrip view={view} open />);
    const list = screen.getByRole("list", { name: "Close flow CELL 记录" });
    expect(Array.from(list.querySelectorAll("strong")).map((item) => item.textContent))
      .toEqual(["Second GO tail", "Second GO first", "First GO tail", "First GO first"]);
    expect(view.currentCellId).toBe(cell.cell_id);
    expect(view.cells.map((item) => item.cellId)).toEqual([cell.cell_id, "go1-tail", "go2-first", "go2-tail"]);
    expect(JSON.stringify(run)).toBe(before);
  });

  it("uses every quiet project tone while keeping tone assignment deterministic", () => {
    const keys = Array.from({ length: 64 }, (_, index) => `project:project-${index}`);
    const tones = keys.map(groupTone);

    expect(groupTone("project:project-a")).toBe(5);
    expect(groupTone("project:project-b")).toBe(6);
    expect(new Set(tones)).toEqual(new Set([1, 2, 3, 4, 5, 6, 7, 8]));
  });

  it("shows source context and expands into roles and CELL facts only", async () => {
    const user = userEvent.setup();
    const run = {
      ...runFixture,
      summary: {
        ...runFixture.summary,
        source_kind: "clk" as const,
        source_project_name: "LCapi 多模型接入",
        run_description: "统一 fallback、限流恢复和模型选择",
      },
    };
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    render(<InteractiveStrip view={view} />);

    expect(screen.getByText("CLK · LCapi 多模型接入")).toBeVisible();
    expect(screen.getByText("统一 fallback、限流恢复和模型选择")).toBeVisible();
    expect(screen.queryByText("SUPERVISOR")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /展开 Close flow/ }));
    expect(screen.getByText("SUPERVISOR")).toBeVisible();
    expect(screen.getByText("qwen3.8-max")).toBeVisible();
    expect(screen.getByText("CELL 01")).toBeVisible();
    expect(screen.getByText("Implement closure")).toBeVisible();
    expect(screen.queryByText(/GO[- ]?001/)).not.toBeInTheDocument();
  });

  it("shows Overwatcher binding, native liveness, and cycle state without claiming work", async () => {
    const user = userEvent.setup();
    const run = {
      ...runFixture,
      roles: [
        ...runFixture.roles,
        {
          ...runFixture.roles[0]!,
          role: "overwatcher" as const,
          role_instance_id: "overwatcher-a",
          agent_runtime: "Codex",
          session_id: "overwatcher-session-a",
          display_state: "ready",
        },
      ],
      overwatch_cycles: [
        {
          cycle_id: "cycle-1",
          overwatcher_role_instance_id: "overwatcher-a",
          session_id: "overwatcher-session-a",
          foreground_turn_id: "turn-1",
          cycle_sequence: 1,
          cadence_seconds: 180,
          plan_revision: 1,
          go_id: "GO-001",
          cell_id: "CELL-001",
          attempt: 1,
          token_sequence: 3,
          token_holder_role_instance_id: "worker-a",
          latest_event_id: "work-started",
          latest_message_id: null,
          checklist_json: "{}",
          anomaly_codes_json: "[]",
          evidence_refs_json: "[]",
          native_active_session_evidence_ref: "evidence/native.json",
          started_at: "2026-09-20T00:03:00Z",
          completed_at: "2026-09-20T00:03:05Z",
          next_cycle_at: "2026-09-20T00:06:05Z",
          binding_revision: 1,
          runtime_revision: 4,
          native_liveness: "IN_PROGRESS",
          cadence_health: "ON_TIME",
          cost_metrics_json: null,
        },
      ],
      overwatcher_native_status_receipts: [
        {
          status_id: "native-1",
          binding_revision: 1,
          role_instance_id: "overwatcher-a",
          session_id: "overwatcher-session-a",
          foreground_turn_id: "turn-1",
          native_liveness: "COMPLETED",
          evidence_path: "evidence/native-completed.json",
          evidence_sha256: "a".repeat(64),
          observed_at: "2026-09-20T00:03:06Z",
        },
      ],
      overwatcher_binding_transitions: [
        {
          transition_id: "binding-1",
          binding_revision: 1,
          transition_type: "BOUND",
          cycle_id: null,
          runtime_revision: 1,
          evidence_ref: "evidence/binding.json",
          occurred_at: "2026-09-20T00:00:00Z",
        },
      ],
    };
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    render(<InteractiveStrip view={view} />);

    await user.click(screen.getByRole("button", { name: /展开 Close flow/ }));
    expect(screen.getByText("OVERWATCHER · 原生会话已结束")).toBeVisible();
    expect(screen.getByText(/绑定 BOUND/)).toBeVisible();
    expect(screen.getByText(/原生 COMPLETED/)).toBeVisible();
    expect(screen.queryByText(/Overwatcher 工作中/)).not.toBeInTheDocument();
  });
});
