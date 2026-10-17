import { useEffect, useRef, useState } from "react";

import type { SlkApi, WebBiSyncResult } from "../api";
import type { SlkSnapshot } from "../useSlkData";
import { canonicalJson } from "../closeout";
import { isArchivedSummary } from "../runPresentation";
import { buildUploadEnvelope } from "./sync";

function uploadId(deviceId: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${deviceId}:${random}`;
}

function runFingerprints(snapshot: SlkSnapshot | undefined, settingsRevision: number) {
  if (!snapshot) return new Map<string, string>();
  const envelope = buildUploadEnvelope(snapshot, "", "");
  return new Map(envelope.runs.map((item) => [item.run.run_id, canonicalJson([settingsRevision, envelope.device, item])]));
}

export function useWebBiSync(api: SlkApi, snapshot: SlkSnapshot | undefined, settingsRevision = 0) {
  const snapshotRef = useRef(snapshot);
  const revisionRef = useRef(settingsRevision);
  const requestAttempt = useRef<() => void>(() => undefined);
  const [state, setState] = useState<{ result: WebBiSyncResult; fingerprints: Map<string, string> }>({ result: { status: "disabled", upload_id: null }, fingerprints: new Map() });
  snapshotRef.current = snapshot;
  revisionRef.current = settingsRevision;
  const formalChanges = canonicalJson(snapshot?.runDetails.filter((run) => run.closeout_summary || isArchivedSummary(run.summary)).map((run) => ({
    run_id: run.run_id, archived: isArchivedSummary(run.summary), archived_at: run.summary.archived_at,
    summary: run.closeout_summary ? [run.closeout_summary.source_id, run.closeout_summary.source_revision, run.closeout_summary.content_sha256] : null,
  })).sort((a, b) => a.run_id.localeCompare(b.run_id)) ?? []);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let queued = false;
    const attempt = async () => {
      const current = snapshotRef.current;
      if (!current || !active) return;
      if (inFlight) { queued = true; return; }
      inFlight = true;
      const fingerprints = runFingerprints(current, revisionRef.current);
      try {
        const result = await api.syncWebBi(buildUploadEnvelope(current, uploadId(current.metadata.device_id), new Date().toISOString()));
        if (active) setState({ result, fingerprints });
      } catch (error) {
        if (active) setState({ result: { status: "failed", upload_id: null, error: error instanceof Error ? error.message : String(error), runs: [...fingerprints.keys()].map((run_id) => ({ run_id, status: "failed" })) }, fingerprints });
      } finally {
        inFlight = false;
        if (queued && active) { queued = false; void attempt(); }
      }
    };
    requestAttempt.current = () => void attempt();
    const timer = window.setInterval(() => void attempt(), 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api]);
  useEffect(() => { requestAttempt.current(); }, [api, Boolean(snapshot), snapshot?.metadata.webbi_sync_enabled, snapshot?.metadata.device_id, formalChanges, settingsRevision]);
  const enabled = snapshot?.metadata.webbi_sync_enabled === true;
  const runs: NonNullable<WebBiSyncResult["runs"]> = [...runFingerprints(snapshot, settingsRevision)].map(([run_id, fingerprint]) => {
    if (!enabled) return { run_id, status: "disabled" };
    const prior = state.result.runs?.find((run) => run.run_id === run_id);
    return state.fingerprints.get(run_id) === fingerprint && prior ? prior : { run_id, status: "pending" };
  });
  const status = !enabled ? "disabled" : runs.some((run) => run.status === "failed") ? "failed"
    : runs.some((run) => run.status === "pending") ? "pending" : state.result.status;
  return { ...state.result, status, runs } satisfies WebBiSyncResult;
}

export const syncStatusLabel = { disabled: "未配置", pending: "待上传", uploaded: "云端已保存", failed: "上传失败" } as const;
