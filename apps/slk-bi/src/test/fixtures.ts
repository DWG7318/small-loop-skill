export const runFixture = {
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
  go_nodes: [],
  roles: [],
  plan_revisions: [],
  events: [],
  token_history: [],
  evidence: [],
};

export const twoRunFixture = {
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
