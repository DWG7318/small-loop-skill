import { describe, expect, it } from "vitest";

import { runFixture } from "../test/fixtures";
import { MESSAGE_CATALOG } from "./catalog";
import {
  projectAuthoritativeMessages,
  projectSupportedAuthoritativeMessages,
  type MessageCatalogEntry,
} from "./messageFeed";

const catalog: MessageCatalogEntry[] = [
  {
    source_kind: "EVENT",
    message_type: "WORK_STARTED",
    label_zh: "Worker 开始工作",
    allowed_roles: ["worker"],
    notification_eligible: true,
  },
  {
    source_kind: "EVENT",
    message_type: "D1_PASSED",
    label_zh: "D1 已通过",
    allowed_roles: ["checker"],
    notification_eligible: true,
  },
  {
    source_kind: "OW_OBSERVATION",
    message_type: "ACTIVITY_UNPROVEN",
    label_zh: "活动无法证实",
    allowed_roles: ["overwatcher"],
    notification_eligible: true,
  },
];

describe("Agent-authored BI message projection", () => {
  it("projects exact event and observation types without classifying display state", () => {
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
          evidence_refs_json: "[]",
          details_json: "{}",
          occurred_at: "2026-09-20T00:00:04Z",
        },
      ],
      roles: [
        ...runFixture.roles,
        {
          ...runFixture.roles[0]!,
          role: "overwatcher" as const,
          role_instance_id: "overwatcher-a",
        },
      ],
    };

    const messages = projectAuthoritativeMessages(run, catalog);

    expect(messages.map((message) => message.message_id)).toEqual([
      "EVENT:work-started",
      "OW_OBSERVATION:observation-a",
    ]);
    expect(messages.map((message) => message.message_type)).toEqual([
      "WORK_STARTED",
      "ACTIVITY_UNPROVEN",
    ]);
    expect(messages.every((message) => !message.message_type.includes("STATUS"))).toBe(true);
  });

  it("rejects an unknown free-text type instead of letting BI classify it", () => {
    const run = {
      ...runFixture,
      events: [{ ...runFixture.events[0]!, event_type: "LOOKS_BUSY" }],
    };
    expect(() => projectAuthoritativeMessages(run, catalog)).toThrow(
      "SLK_BI_MESSAGE_TYPE_INVALID",
    );
  });

  it("rejects a known type authored by the wrong role", () => {
    const run = {
      ...runFixture,
      events: [{ ...runFixture.events[0]!, event_type: "D1_PASSED" }],
    };
    expect(() => projectAuthoritativeMessages(run, catalog)).toThrow(
      "SLK_BI_MESSAGE_ROLE_INVALID",
    );
  });

  it("accepts current Checker session recovery and Supervisor role closure facts", () => {
    const run = {
      ...runFixture,
      events: [
        {
          ...runFixture.events[0]!,
          event_id: "session-rebound",
          event_type: "SESSION_REBOUND",
          author_role_instance_id: "checker-a",
        },
        {
          ...runFixture.events[0]!,
          event_id: "role-closed",
          event_type: "ROLE_CLOSED",
          author_role_instance_id: "supervisor-a",
          occurred_at: "2026-09-20T00:00:05Z",
        },
      ],
    };

    expect(
      projectAuthoritativeMessages(run, MESSAGE_CATALOG).map(({ message_type }) => message_type),
    ).toEqual(["SESSION_REBOUND", "ROLE_CLOSED"]);
  });

  it("omits an unsupported historical event without hiding valid Agent-authored messages", () => {
    const run = {
      ...runFixture,
      summary: {
        ...runFixture.summary,
        slk_version: "4.0.0",
      },
      events: [
        ...runFixture.events,
        {
          ...runFixture.events[0]!,
          event_id: "legacy-checker-rework",
          event_type: "REWORK_REQUESTED",
          author_role_instance_id: "checker-a",
        },
      ],
    };

    expect(
      projectSupportedAuthoritativeMessages(run, MESSAGE_CATALOG).map(({ message_id }) => message_id),
    ).toEqual(["EVENT:work-started"]);
  });

  it("does not hide the same wrong-role event from a current Run", () => {
    const run = {
      ...runFixture,
      events: [
        ...runFixture.events,
        {
          ...runFixture.events[0]!,
          event_id: "current-checker-rework",
          event_type: "REWORK_REQUESTED",
          author_role_instance_id: "checker-a",
        },
      ],
    };

    expect(() => projectSupportedAuthoritativeMessages(run, MESSAGE_CATALOG)).toThrow(
      "SLK_BI_MESSAGE_ROLE_INVALID",
    );
  });

  it("does not turn normal Overwatcher cycles or elapsed time into messages", () => {
    const run = {
      ...runFixture,
      overwatch_cycles: [
        {
          cycle_id: "cycle-1",
          overwatcher_role_instance_id: "overwatcher-a",
          session_id: "ow-session",
          foreground_turn_id: "turn-1",
          cycle_sequence: 1,
          cadence_seconds: 600,
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
          native_active_session_evidence_ref: "evidence-a",
          started_at: "2026-09-20T00:00:04Z",
          completed_at: "2026-09-20T00:00:05Z",
          next_cycle_at: "2026-09-20T00:10:05Z",
          binding_revision: 1,
          runtime_revision: 1,
          native_liveness: "IN_PROGRESS",
          cadence_health: "ON_TIME",
          cost_metrics_json: null,
        },
      ],
    };
    expect(projectAuthoritativeMessages(run, catalog)).toHaveLength(1);
  });
});
