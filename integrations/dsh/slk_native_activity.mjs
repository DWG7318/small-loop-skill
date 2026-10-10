import { createHash, randomUUID } from "node:crypto";
import { closeSync, existsSync, fsyncSync, openSync, renameSync, unlinkSync, writeFileSync } from "node:fs";

export const name = "slk-native-activity";
export const inject = ["agents"];

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
  let lastEvent;
  let sample;
  let sampleError;

  const write = () => {
    if (!nativeTaskId || !lastEvent) return;
    writeAtomic(binding.output, {
      schema_version: "slk.native-task-activity/v1",
      ...binding.value,
      native_task_id: nativeTaskId,
      status: sampleError ? "UNKNOWN" : status,
      sequence,
      observed_at: sample?.observed_at ?? lastEvent.observed_at,
      last_event: { ...lastEvent, tail: eventTail },
      waiting_on: status === "RUNNING" ? "DSH_AGENT" : null,
      ...(sample ? { sample } : {}),
      ...(sampleError ? { error: sampleError } : {}),
    });
  };

  const sampleLive = () => {
    if (!nativeTaskId || !ctx.agents?.get) return;
    const fail = (error) => { sampleError = error; write(); };
    sample = { source: "DSH_LIVE_AGENT_REGISTRY", native_task_id: nativeTaskId,
      observed_at: new Date().toISOString() };
    try {
      const agent = ctx.agents.get(nativeTaskId);
      if (!agent) return fail("DSH_AGENT_NOT_REGISTERED");
      if (String(agent.session.id) !== nativeTaskId) return fail("DSH_SESSION_IDENTITY_MISMATCH");
      if (ctx.get("workspaceRegistry")?.archivedSessionIds?.includes(nativeTaskId)) {
        return fail("DSH_SESSION_ARCHIVED");
      }
      status = String(agent.status).toUpperCase();
      sampleError = undefined;
      write();
    } catch {
      fail("DSH_STATUS_QUERY_UNAVAILABLE");
    }
  };

  const publish = (kind, detail) => {
    if (!nativeTaskId) return;
    sequence += 1;
    const observedAt = new Date().toISOString();
    const detailSha256 = createHash("sha256").update(String(detail)).digest("hex");
    eventTail = [
      ...eventTail,
      { kind, sequence, observed_at: observedAt, detail_sha256: detailSha256 },
    ].slice(-12);
    lastEvent = { kind, sequence, observed_at: observedAt, detail_sha256: detailSha256 };
    write();
  };

  ctx.on("agent/status", ({ agent, status: next }) => {
    if (nativeTaskId && String(agent.session.id) !== nativeTaskId) return;
    const initial = !nativeTaskId;
    nativeTaskId = String(agent.session.id);
    const eventStatus = String(next).toUpperCase();
    if (!sample) status = eventStatus;
    publish("DSH_AGENT_STATUS", eventStatus);
    if (initial) sampleLive();
  });
  ctx.on("session/event", (session, event) => {
    const sessionId = String(session.id);
    if (!nativeTaskId || sessionId !== nativeTaskId) return;
    publish("DSH_SESSION_EVENT", event?.type ?? "unknown");
  });
  if (ctx.effect && ctx.agents?.get) {
    ctx.effect(() => {
      const timer = setInterval(sampleLive, 60000);
      return () => clearInterval(timer);
    });
  }
}
