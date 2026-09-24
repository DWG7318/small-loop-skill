import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildRunStripView } from "../runPresentation";
import { runFixture, twoRunFixture } from "../test/fixtures";
import { groupTone, RunStrip } from "./RunStrip";

describe("RunStrip", () => {
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
    render(<RunStrip view={view} />);

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
    render(<RunStrip view={view} />);

    await user.click(screen.getByRole("button", { name: /展开 Close flow/ }));
    expect(screen.getByText("OVERWATCHER · 原生会话已结束")).toBeVisible();
    expect(screen.getByText(/绑定 BOUND/)).toBeVisible();
    expect(screen.getByText(/原生 COMPLETED/)).toBeVisible();
    expect(screen.queryByText(/Overwatcher 工作中/)).not.toBeInTheDocument();
  });
});
