import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RoleProjection } from "../contracts";
import { Inspector } from "./Inspector";

const checker: RoleProjection = {
  role: "checker",
  role_instance_id: "checker-b",
  agent_runtime: "OCRV",
  provider: "Qwen",
  model: "qwen-checker",
  reasoning: "medium",
  session_id: "checker-session-a2",
  lifecycle: "active",
  predecessor_role_instance_id: "checker-a",
  successor_role_instance_id: null,
  current_go_id: "GO-001",
  current_cell_id: "CELL-001",
  created_at: "2026-09-20T00:00:03Z",
  takeover_at: "2026-09-20T00:00:03Z",
  exited_at: null,
  endpoints: [
    {
      endpoint_version: 2,
      transport_adapter: "ocrv",
      host_identity: "local",
      session_id: "checker-session-a2",
      state: "active",
      created_at: "2026-09-20T00:00:03Z",
      retired_at: null,
    },
  ],
  display_state: "ready",
};

describe("Inspector", () => {
  it("shows role provenance without credentials", () => {
    render(<Inspector selection={{ kind: "role", value: checker }} />);
    expect(screen.getByText("qwen-checker")).toBeVisible();
    expect(screen.getAllByText("checker-session-a2")).toHaveLength(2);
    expect(screen.getByText("Replaced checker-a")).toBeVisible();
    expect(screen.queryByText(/credential/i)).not.toBeInTheDocument();
  });
});
