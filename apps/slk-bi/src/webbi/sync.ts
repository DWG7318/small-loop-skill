import type { SlkSnapshot } from "../useSlkData";
import { MESSAGE_CATALOG } from "../messages/catalog";
import { projectAuthoritativeMessages } from "../messages/messageFeed";
import type { WebBiUploadEnvelope } from "./contracts";

function orderedRuns(snapshot: SlkSnapshot) {
  const details = new Map(snapshot.runDetails.map((run) => [run.run_id, run]));
  return snapshot.runs.runs.flatMap((summary) => {
    const run = details.get(summary.run_id);
    return run ? [run] : [];
  });
}

export function buildUploadEnvelope(
  snapshot: SlkSnapshot,
  uploadId: string,
  generatedAt: string,
  uploadedMessageIds: ReadonlySet<string> = new Set(),
): WebBiUploadEnvelope {
  return {
    schema_version: "slk.bi.upload/v1",
    bi_version: "1.1.0",
    upload_id: uploadId,
    generated_at: generatedAt,
    device: {
      device_id: snapshot.metadata.device_id,
      device_name: snapshot.metadata.device_name,
    },
    runs: orderedRuns(snapshot).map((run) => ({
      run,
      messages: projectAuthoritativeMessages(run, MESSAGE_CATALOG).filter(
        ({ message_id }) => !uploadedMessageIds.has(message_id),
      ),
    })),
  };
}

export function uploadFingerprint(snapshot: SlkSnapshot) {
  return JSON.stringify({
    bi_version: snapshot.metadata.bi_version,
    device_id: snapshot.metadata.device_id,
    device_name: snapshot.metadata.device_name,
    runs: orderedRuns(snapshot),
  });
}
