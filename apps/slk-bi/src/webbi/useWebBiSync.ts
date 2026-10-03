import { useEffect, useRef } from "react";

import type { SlkApi } from "../api";
import type { SlkSnapshot } from "../useSlkData";
import { buildUploadEnvelope, uploadFingerprint } from "./sync";

function uploadId(deviceId: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${deviceId}:${random}`;
}

export function useWebBiSync(api: SlkApi, snapshot: SlkSnapshot | undefined) {
  const snapshotRef = useRef(snapshot);
  const lastUploadedFingerprint = useRef<string | undefined>(undefined);
  const uploadedMessageIds = useRef(new Set<string>());
  snapshotRef.current = snapshot;

  useEffect(() => {
    if (!snapshot?.metadata.webbi_sync_enabled) return;
    let active = true;
    const attempt = async () => {
      const current = snapshotRef.current;
      if (!current?.metadata.webbi_sync_enabled) return;
      const fingerprint = uploadFingerprint(current);
      if (fingerprint === lastUploadedFingerprint.current) return;
      const envelope = buildUploadEnvelope(
        current,
        uploadId(current.metadata.device_id),
        new Date().toISOString(),
        uploadedMessageIds.current,
      );
      const result = await api.syncWebBi(envelope);
      if (active && result.status === "uploaded") {
        lastUploadedFingerprint.current = fingerprint;
        for (const { messages } of envelope.runs) {
          for (const { message_id } of messages) uploadedMessageIds.current.add(message_id);
        }
      }
    };
    void attempt().catch(() => undefined);
    const timer = window.setInterval(() => void attempt().catch(() => undefined), 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api, snapshot?.metadata.webbi_sync_enabled]);
}
