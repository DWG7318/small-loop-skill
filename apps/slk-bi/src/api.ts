import { invoke } from "@tauri-apps/api/core";

import {
  type EvidenceView,
  type EventsView,
  type GraphView,
  type PlansView,
  type ProjectsView,
  type RolesView,
  type RunsView,
  type RunView,
  parseEvidenceProjection,
  parseEventsProjection,
  parseGraphProjection,
  parsePlansProjection,
  parseProjectsProjection,
  parseRolesProjection,
  parseRunProjection,
  parseRunsProjection,
} from "./contracts";
import type { WebBiUploadEnvelope } from "./webbi/contracts";

export interface SlkApi {
  metadata(): Promise<BiMetadata>;
  projects(): Promise<ProjectsView>;
  runs(projectId?: string): Promise<RunsView>;
  run(runId: string): Promise<RunView>;
  graph(runId: string): Promise<GraphView>;
  roles(runId: string): Promise<RolesView>;
  plans(runId: string): Promise<PlansView>;
  events(runId: string): Promise<EventsView>;
  evidence(runId: string): Promise<EvidenceView>;
  syncWebBi(payload: WebBiUploadEnvelope): Promise<WebBiSyncResult>;
}

export interface WebBiSyncResult {
  status: "disabled" | "uploaded";
  upload_id: string | null;
}

export interface BiMetadata {
  schema_version: "slk.bi.metadata/v1";
  bi_version: import("./version").BiVersion;
  device_id: string;
  device_name: string;
  webbi_sync_enabled: boolean;
}

export const tauriApi: SlkApi = {
  metadata: async () => await invoke<BiMetadata>("metadata"),
  projects: async () => parseProjectsProjection(await invoke("projects")),
  runs: async (projectId) =>
    parseRunsProjection(await invoke("runs", { projectId: projectId ?? null })),
  run: async (runId) => parseRunProjection(await invoke("run", { runId })),
  graph: async (runId) => parseGraphProjection(await invoke("graph", { runId })),
  roles: async (runId) => parseRolesProjection(await invoke("roles", { runId })),
  plans: async (runId) => parsePlansProjection(await invoke("plans", { runId })),
  events: async (runId) => parseEventsProjection(await invoke("events", { runId })),
  evidence: async (runId) => parseEvidenceProjection(await invoke("evidence", { runId })),
  syncWebBi: async (payload) => await invoke<WebBiSyncResult>("sync_webbi", { payload }),
};
