import { describe, expect, it } from "vitest";

import type { SlkSnapshot } from "../useSlkData";
import { twoRunFixture } from "../test/fixtures";
import { buildUploadEnvelope, uploadFingerprint } from "./sync";

function snapshot(): SlkSnapshot {
  return {
    metadata: {
      schema_version: "slk.bi.metadata/v1",
      bi_version: "1.1.0",
      device_id: "device-a",
      device_name: "Workstation A",
      webbi_sync_enabled: true,
    },
    ...twoRunFixture,
  };
}

describe("desktop BI WebBI upload", () => {
  it("builds the bounded 1.1 envelope from the same Run views BI already reads", () => {
    const envelope = buildUploadEnvelope(
      snapshot(),
      "upload-a",
      "2026-10-04T00:00:00Z",
    );
    expect(envelope.schema_version).toBe("slk.bi.upload/v1");
    expect(envelope.bi_version).toBe("1.1.0");
    expect(envelope.device).toEqual({ device_id: "device-a", device_name: "Workstation A" });
    expect(envelope.runs.map(({ run }) => run.run_id)).toEqual(["run-a", "run-b"]);
    expect(envelope.runs[0]?.messages.map(({ message_id }) => message_id)).toEqual([
      "EVENT:work-started",
    ]);
  });

  it("keeps the fingerprint unchanged for polling and elapsed wall-clock time", () => {
    const current = snapshot();
    expect(uploadFingerprint(current)).toBe(uploadFingerprint({ ...current }));
  });

  it("changes the fingerprint when a new Agent-authored message appears", () => {
    const current = snapshot();
    const changed: SlkSnapshot = {
      ...current,
      runDetails: current.runDetails.map((run, index) =>
        index
          ? run
          : {
              ...run,
              events: [
                ...run.events,
                {
                  ...run.events[0]!,
                  event_id: "work-progress",
                  event_type: "WORK_PROGRESS",
                  occurred_at: "2026-10-04T00:01:00Z",
                },
              ],
            }),
    };
    expect(uploadFingerprint(changed)).not.toBe(uploadFingerprint(current));
  });

  it("sends only message ids not confirmed by an earlier successful upload", () => {
    const current = snapshot();
    const first = buildUploadEnvelope(current, "upload-a", "2026-10-04T00:00:00Z");
    const uploaded = new Set(first.runs.flatMap(({ messages }) => messages.map(({ message_id }) => message_id)));
    const second = buildUploadEnvelope(
      current,
      "upload-b",
      "2026-10-04T00:01:00Z",
      uploaded,
    );
    expect(second.runs.every(({ messages }) => messages.length === 0)).toBe(true);
  });
});
