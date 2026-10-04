import { createHash, randomUUID } from "node:crypto";
import { closeSync, existsSync, fsyncSync, openSync, renameSync, unlinkSync, writeFileSync } from "node:fs";

export const name = "slk-native-activity";

function context() {
  const output = process.env.SLK_NATIVE_ACTIVITY_PATH;
  const raw = process.env.SLK_NATIVE_ACTIVITY_CONTEXT;
  if (!output || !raw) return undefined;
  const value = JSON.parse(raw);
  const fields = ["adapter", "run_id", "cell_id", "message_id"];
  if (Object.keys(value).sort().join(",") !== fields.sort().join(",")) {
    throw new Error("slk-native-activity: context is not closed");
  }
  if (!fields.every((field) => typeof value[field] === "string" && value[field] !== "")) {
    throw new Error("slk-native-activity: context identity is incomplete");
  }
  return { output, value };
}

function boundedSleep(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

export function writeAtomic(path, value, operations = {}) {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const rename = operations.rename ?? renameSync;
  const sleep = operations.sleep ?? boundedSleep;
  let replaced = false;
  try {
    writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
    const descriptor = openSync(temporary, "r+");
    try {
      fsyncSync(descriptor);
    } finally {
      closeSync(descriptor);
    }
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        rename(temporary, path);
        replaced = true;
        return;
      } catch (error) {
        if (!["EBUSY", "EPERM"].includes(error?.code) || attempt === 2) throw error;
        sleep(10 * (attempt + 1));
      }
    }
  } finally {
    if (!replaced && existsSync(temporary)) unlinkSync(temporary);
  }
}

export function apply(ctx) {
  const binding = context();
  if (!binding) return;
  let sequence = 0;
  let status = "PENDING";
  let nativeTaskId;
  let eventTail = [];

  const publish = (kind, detail) => {
    if (!nativeTaskId) return;
    sequence += 1;
    const observedAt = new Date().toISOString();
    const detailSha256 = createHash("sha256").update(String(detail)).digest("hex");
    eventTail = [
      ...eventTail,
      { kind, sequence, observed_at: observedAt, detail_sha256: detailSha256 },
    ].slice(-12);
    writeAtomic(binding.output, {
      schema_version: "slk.native-task-activity/v1",
      ...binding.value,
      native_task_id: nativeTaskId,
      status,
      sequence,
      observed_at: observedAt,
      last_event: {
        kind,
        sequence,
        detail_sha256: detailSha256,
        tail: eventTail,
      },
      waiting_on: status === "RUNNING" ? "DSH_AGENT" : null,
    });
  };

  ctx.on("agent/status", ({ agent, status: next }) => {
    nativeTaskId = String(agent.session.id);
    status = String(next).toUpperCase();
    publish("DSH_AGENT_STATUS", status);
  });
  ctx.on("session/event", (session, event) => {
    const sessionId = String(session.id);
    if (nativeTaskId && sessionId !== nativeTaskId) return;
    nativeTaskId = sessionId;
    publish("DSH_SESSION_EVENT", event?.type ?? "unknown");
  });
}
