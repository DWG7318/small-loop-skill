import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EventProjection } from "../contracts";
import { Timeline } from "./Timeline";

const events: EventProjection[] = [
  {
    event_id: "work-started",
    event_type: "WORK_STARTED",
    author_role_instance_id: "worker-a",
    go_id: "GO-001",
    cell_id: "CELL-001",
    attempt: 1,
    details_json: '{"summary":"Original fact"}',
    corrects_event_id: null,
    occurred_at: "2026-09-20T00:00:03Z",
  },
  {
    event_id: "work-correction",
    event_type: "WORK_PROGRESS",
    author_role_instance_id: "worker-a",
    go_id: "GO-001",
    cell_id: "CELL-001",
    attempt: 1,
    details_json: '{"summary":"Corrected fact"}',
    corrects_event_id: "work-started",
    occurred_at: "2026-09-20T00:00:04Z",
  },
];

describe("Timeline", () => {
  it("preserves the original event beside its correction", () => {
    render(<Timeline events={events} onSelect={() => undefined} />);
    expect(screen.getByText("Original fact")).toBeVisible();
    expect(screen.getByText("Correction of work-started")).toBeVisible();
    expect(screen.getByText("Corrected fact")).toBeVisible();
  });
});
