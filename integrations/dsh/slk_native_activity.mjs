import { createHash } from "node:crypto";
import { closeSync, fsyncSync, openSync, renameSync, writeFileSync } from "node:fs";

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

function writeAtomic(path, value) {
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  const descriptor = openSync(temporary, "r+");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
  renameSync(temporary, path);
}

export function apply(ctx) {
  const binding = context();
  if (!binding) return;
  let sequence = 0;
  let status = "PENDING";
  let nativeTaskId;

  const publish = (kind, detail) => {
    if (!nativeTaskId) return;
    sequence += 1;
    writeAtomic(binding.output, {
      schema_version: "slk.native-task-activity/v1",
      ...binding.value,
      native_task_id: nativeTaskId,
      status,
      sequence,
      observed_at: new Date().toISOString(),
      last_event: {
        kind,
        sequence,
        detail_sha256: createHash("sha256").update(String(detail)).digest("hex"),
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
