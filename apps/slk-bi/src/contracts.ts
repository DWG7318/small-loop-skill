type JsonObject = Record<string, unknown>;

export interface ProjectSummary {
  project_id: string;
  name: string;
  repository_url: string | null;
  last_known_path: string;
  run_count: number;
}

export interface RunSummary {
  run_id: string;
  project_id: string;
  run_name: string;
  run_description: string;
  slk_version: string;
  source_kind: "solo" | "clk" | "glk";
  source_project_name: string | null;
  goal: string;
  state: string;
  current_plan_revision: number;
  closure_state: string;
  created_at: string;
  closed_at: string | null;
  archive_reason: string | null;
  archived_at: string | null;
  superseded_by_run_id: string | null;
}

export interface CellProjection {
  cell_id: string;
  ordinal: number;
  title: string;
  objective: string;
  state: string;
  attempt: number;
  outcome: string | null;
}

export interface GoProjection {
  go_id: string;
  ordinal: number;
  title: string;
  objective: string;
  state: string;
  outcome: string | null;
  cell_nodes: CellProjection[];
}

export interface EndpointProjection {
  endpoint_version: number;
  transport_adapter: string;
  host_identity: string;
  session_id: string;
  state: string;
  created_at: string;
  retired_at: string | null;
}

export interface RoleProjection {
  role: "supervisor" | "checker" | "worker";
  role_instance_id: string;
  agent_runtime: string;
  provider: string;
  model: string;
  reasoning: string;
  session_id: string;
  lifecycle: string;
  predecessor_role_instance_id: string | null;
  successor_role_instance_id: string | null;
  current_go_id: string | null;
  current_cell_id: string | null;
  created_at: string;
  takeover_at: string | null;
  exited_at: string | null;
  endpoints: EndpointProjection[];
  display_state: string;
}

export interface PlanRevisionProjection {
  revision: number;
  author_role_instance_id: string;
  reason: string;
  previous_revision: number | null;
  created_at: string;
}

export interface EventProjection {
  event_id: string;
  event_type: string;
  author_role_instance_id: string;
  go_id: string | null;
  cell_id: string | null;
  attempt: number | null;
  details_json: string;
  corrects_event_id: string | null;
  occurred_at: string;
}

export interface TokenProjection {
  token_sequence: number;
  from_role_instance_id: string | null;
  to_role_instance_id: string;
  go_id: string | null;
  cell_id: string | null;
  message_id: string | null;
  event_type: string;
  occurred_at: string;
}

export interface EvidenceProjection {
  evidence_id: string;
  evidence_type: string;
  stored_path: string;
  sha256: string;
  byte_length: number;
  producing_role_instance_id: string;
  go_id: string | null;
  cell_id: string | null;
  created_at: string;
}

export interface ProjectsView {
  schema_version: "slk.bi.projects/v1";
  projects: ProjectSummary[];
}

export interface RunsView {
  schema_version: "slk.bi.runs/v1";
  runs: RunSummary[];
}

export interface RunView {
  schema_version: "slk.bi.run/v1";
  run_id: string;
  summary: RunSummary;
  boundaries_json: string;
  go_nodes: GoProjection[];
  roles: RoleProjection[];
  plan_revisions: PlanRevisionProjection[];
  events: EventProjection[];
  token_history: TokenProjection[];
  evidence: EvidenceProjection[];
}

export interface GraphView {
  schema_version: "slk.bi.graph/v1";
  run_id: string;
  go_nodes: GoProjection[];
}

export interface RolesView {
  schema_version: "slk.bi.roles/v1";
  run_id: string;
  roles: RoleProjection[];
}

export interface PlansView {
  schema_version: "slk.bi.plans/v1";
  run_id: string;
  plan_revisions: PlanRevisionProjection[];
}

export interface EventsView {
  schema_version: "slk.bi.events/v1";
  run_id: string;
  events: EventProjection[];
}

export interface EvidenceView {
  schema_version: "slk.bi.evidence/v1";
  run_id: string;
  evidence: EvidenceProjection[];
}

function object(value: unknown): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("SLK_BI_PROJECTION_INVALID");
  }
  return value as JsonObject;
}

function schema(value: unknown, expected: string): JsonObject {
  const projection = object(value);
  if (projection.schema_version !== expected) {
    throw new Error(`SLK_BI_SCHEMA_UNSUPPORTED:${String(projection.schema_version)}`);
  }
  return projection;
}

function collection(projection: JsonObject, key: string): void {
  if (!Array.isArray(projection[key])) throw new Error("SLK_BI_PROJECTION_INVALID");
}

export function parseProjectsProjection(value: unknown): ProjectsView {
  const projection = schema(value, "slk.bi.projects/v1");
  collection(projection, "projects");
  return projection as unknown as ProjectsView;
}

export function parseRunsProjection(value: unknown): RunsView {
  const projection = schema(value, "slk.bi.runs/v1");
  collection(projection, "runs");
  return projection as unknown as RunsView;
}

export function parseRunProjection(value: unknown): RunView {
  const projection = schema(value, "slk.bi.run/v1");
  object(projection.summary);
  for (const key of ["go_nodes", "roles", "plan_revisions", "events", "token_history", "evidence"]) {
    collection(projection, key);
  }
  return projection as unknown as RunView;
}

function parseCollection<T>(value: unknown, expected: string, key: string): T {
  const projection = schema(value, expected);
  collection(projection, key);
  return projection as T;
}

export const parseGraphProjection = (value: unknown) =>
  parseCollection<GraphView>(value, "slk.bi.graph/v1", "go_nodes");
export const parseRolesProjection = (value: unknown) =>
  parseCollection<RolesView>(value, "slk.bi.roles/v1", "roles");
export const parsePlansProjection = (value: unknown) =>
  parseCollection<PlansView>(value, "slk.bi.plans/v1", "plan_revisions");
export const parseEventsProjection = (value: unknown) =>
  parseCollection<EventsView>(value, "slk.bi.events/v1", "events");
export const parseEvidenceProjection = (value: unknown) =>
  parseCollection<EvidenceView>(value, "slk.bi.evidence/v1", "evidence");
