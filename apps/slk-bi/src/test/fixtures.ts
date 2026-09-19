import type { SlkApi } from "../api";
import type { ProjectsView, RunsView, RunView } from "../contracts";

export const runFixture: RunView = {
  schema_version: "slk.bi.run/v1",
  run_id: "run-a",
  summary: {
    run_id: "run-a",
    project_id: "project-a",
    goal: "Acceptance A",
    state: "active",
    current_plan_revision: 1,
    closure_state: "open",
    created_at: "2026-09-20T00:00:00Z",
    closed_at: null,
  },
  boundaries_json: "{}",
  go_nodes: [
    {
      go_id: "GO-001",
      ordinal: 1,
      title: "Close flow",
      objective: "Close one serial flow",
      state: "active",
      outcome: null,
      cell_nodes: [
        {
          cell_id: "CELL-001",
          ordinal: 1,
          title: "Implement closure",
          objective: "Produce the candidate",
          state: "active",
          attempt: 1,
          outcome: null,
        },
      ],
    },
  ],
  roles: [
    {
      role: "worker",
      role_instance_id: "worker-a",
      agent_runtime: "Codex",
      provider: "OpenAI",
      model: "gpt-5.6-terra",
      reasoning: "high",
      session_id: "worker-session-a",
      lifecycle: "active",
      predecessor_role_instance_id: null,
      successor_role_instance_id: null,
      current_go_id: "GO-001",
      current_cell_id: "CELL-001",
      created_at: "2026-09-20T00:00:01Z",
      takeover_at: null,
      exited_at: null,
      endpoints: [
        {
          endpoint_version: 1,
          transport_adapter: "native",
          host_identity: "local",
          session_id: "worker-session-a",
          state: "active",
          created_at: "2026-09-20T00:00:01Z",
          retired_at: null,
        },
      ],
      display_state: "working",
    },
  ],
  plan_revisions: [],
  events: [
    {
      event_id: "work-started",
      event_type: "WORK_STARTED",
      author_role_instance_id: "worker-a",
      go_id: "GO-001",
      cell_id: "CELL-001",
      attempt: 1,
      details_json: "{}",
      corrects_event_id: null,
      occurred_at: "2026-09-20T00:00:03Z",
    },
  ],
  token_history: [
    {
      token_sequence: 3,
      from_role_instance_id: "checker-a",
      to_role_instance_id: "worker-a",
      go_id: "GO-001",
      cell_id: "CELL-001",
      message_id: "message-3",
      event_type: "TOKEN_HANDED_OFF",
      occurred_at: "2026-09-20T00:00:02Z",
    },
  ],
  evidence: [],
};

export const twoRunFixture: { projects: ProjectsView; runs: RunsView } = {
  projects: {
    schema_version: "slk.bi.projects/v1",
    projects: [
      {
        project_id: "project-a",
        name: "Project A",
        repository_url: null,
        last_known_path: "D:/ProjectA",
        run_count: 2,
      },
    ],
  },
  runs: {
    schema_version: "slk.bi.runs/v1",
    runs: [
      runFixture.summary,
      { ...runFixture.summary, run_id: "run-b", goal: "Acceptance B" },
    ],
  },
};

export const fixtureApi: SlkApi = {
  projects: async () => twoRunFixture.projects,
  runs: async () => twoRunFixture.runs,
  run: async () => runFixture,
  graph: async () => ({
    schema_version: "slk.bi.graph/v1" as const,
    run_id: "run-a",
    go_nodes: runFixture.go_nodes,
  }),
  roles: async () => ({
    schema_version: "slk.bi.roles/v1" as const,
    run_id: "run-a",
    roles: runFixture.roles,
  }),
  plans: async () => ({
    schema_version: "slk.bi.plans/v1" as const,
    run_id: "run-a",
    plan_revisions: runFixture.plan_revisions,
  }),
  events: async () => ({
    schema_version: "slk.bi.events/v1" as const,
    run_id: "run-a",
    events: runFixture.events,
  }),
  evidence: async () => ({
    schema_version: "slk.bi.evidence/v1" as const,
    run_id: "run-a",
    evidence: runFixture.evidence,
  }),
};
