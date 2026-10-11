import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const name = "slk-native-probe";
// Optional services are queried rather than injected: a custom profile lacking
// one is explicitly UNKNOWN, not prevented from starting or silently repaired.
const installed = Symbol.for("slk.native-probe.host.v1");
export const intervalMilliseconds = 60_000;

export async function readArchive(ctx) {
  const workspace = ctx.get("workspaceRegistry");
  if (workspace) {
    const archive = workspace.archivedSessionIds;
    if (!Array.isArray(archive)) throw new Error("native archive set unavailable");
    return { ids: archive, source: "DSH_WORKSPACE_REGISTRY" };
  }
  // Headless intentionally does not mount the Web workspace service. Read its
  // actual routed JSON medium, without mounting/initializing a domain or BI.
  const storage = ctx.get("storage");
  const config = storage?.domain?.config;
  if (!config || (config.routes?.workspace ?? config.backend) !== "json") throw new Error("native archive route unavailable");
  const backend = storage.backend.get("json");
  if (typeof backend.root !== "string") throw new Error("native archive medium unavailable");
  const path = join(backend.root, "workspace.json");
  let text;
  try { text = await readFile(path, "utf8"); } catch (error) { if (error.code === "ENOENT") return { ids: [], source: `DSH_NATIVE_WORKSPACE_DOMAIN_ABSENT:${path}` }; throw error; }
  const value = JSON.parse(text);
  if (value?.unit?.name !== "workspace" || value?.unit?.version !== 2 || !value.global || (value.global.archivedSessionIds !== undefined && !Array.isArray(value.global.archivedSessionIds))) throw new Error("native workspace domain identity invalid");
  return { ids: value.global.archivedSessionIds ?? [], source: path };
}

export async function collect(ctx, events = new Map()) {
  const query = ctx.get("sessionQuery");
  const persistence = ctx.get("sessionPersistence");
  if (!query?.listSessions || !persistence?.list) {
    return { coverage: "UNKNOWN", total: 0, archived: 0, omitted: 0, objects: [], error: "DSH_NATIVE_CORPUS_OR_ARCHIVE_SERVICE_UNAVAILABLE" };
  }
  try {
    const archive = await readArchive(ctx);
    const records = await query.listSessions();
    const stored = new Map((await persistence.list()).map((record) => [String(record.header.id), record]));
    const archived = new Set(archive.ids.map(String));
    const objects = [];
    let archiveCount = 0;
    let coverage = "COMPLETE";
    for (const record of records) {
      const id = String(record.header.id);
      if (archived.has(id)) { archiveCount += 1; continue; }
      const agent = ctx.get("agents")?.get(id);
      const object = { session_id: id, status: "UNKNOWN", live: record.live === true, persisted: record.persisted === true };
      if (agent && String(agent.session.id) === id) object.status = String(agent.status).toUpperCase();
      if (stored.has(id)) {
        const snapshot = stored.get(id);
        object.native_revision = String(snapshot.revision);
        if (typeof snapshot.sizeBytes === "number") object.source_bytes = snapshot.sizeBytes;
        if (persistence.resolveCurrentLog) {
          object.source = await persistence.resolveCurrentLog(id) ?? "";
          if (object.source) {
            const native = await stat(object.source, { bigint: true });
            object.source_identity = `native-stat:${native.dev}:${native.ino}:${native.birthtimeNs}`;
            object.source_bytes = Number(native.size);
            object.source_modified_at = native.mtime.toISOString();
          }
        }
      }
      const event = events.get(id);
      if (event) Object.assign(object, event);
      objects.push(object);
    }
    // Forget event metadata for objects no longer present or now archived.
    const included = new Set(objects.map((object) => object.session_id));
    for (const id of events.keys()) if (!included.has(id)) events.delete(id);
    return { coverage, total: objects.length, archived: archiveCount, archive_source: archive.source, omitted: 0, objects };
  } catch (error) {
    return { coverage: "UNKNOWN", total: 0, archived: 0, omitted: 0, objects: [], error: `DSH_NATIVE_CORPUS_QUERY_FAILED:${error?.code ?? error?.name ?? "Error"}` };
  }
}

export function ingest(host, executable = join(dirname(fileURLToPath(import.meta.url)), "slk-native-probe.exe")) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ["--tool", "dsh", "ingest"], { windowsHide: true, stdio: ["pipe", "ignore", "pipe"] });
    let error = "";
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (data) => { error += data; });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`native probe helper ${code}: ${error}`)));
    child.stdin.on("error", reject);
    child.stdin.end(JSON.stringify(host));
  });
}

export function startProbe(ctx, options = {}) {
  // Compatibility unit harnesses may supply only the old event API. A real
  // Cordis host has effect/get; do not invent a sampler when they are absent.
  if (!ctx.effect || !ctx.get) return;
  if (ctx[installed]) return;
  ctx[installed] = true;
  const events = new Map();
  let chain = Promise.resolve();
  let latest;
  const sample = (lifecycle = "ACTIVE") => {
    if (lifecycle !== "EXITING") options.onSample?.();
    chain = chain.then(async () => {
      // Cordis disposes dependencies before some final plugin effects. Exit
      // must retain the previous actual sample, not erase it or relabel its
      // RUNNING status as a newly observed terminal state.
      if (lifecycle !== "EXITING" || !latest) latest = { ...(await collect(ctx, events)), observed_at: new Date().toISOString() };
      await (options.ingest ?? ingest)({ id: "", pid: process.pid, process_created: "", device: "", native_home: process.env.DSH_HOME ?? join(homedir(), ".dsh"), lifecycle, lifecycle_at: new Date().toISOString(), ...latest });
    }).catch((error) => { ctx.logger?.warn?.(`slk-native-probe: sample not persisted: ${String(error)}`); });
    return chain;
  };
  ctx.on("session/event", (session, event) => {
    // Native emission time is distinct from an event's own asserted timestamp.
    const kind = typeof event?.type === "string" ? event.type : "unknown";
    const id = String(session.id);
    const sequence = typeof event?.seq === "number" ? event.seq : (events.get(id)?.event_count ?? 0) + 1;
    events.set(id, { event_type: kind, event_at: new Date().toISOString(), event_sha256: createHash("sha256").update(JSON.stringify(event ?? null)).digest("hex"), event_source: "DSH_NATIVE_EMISSION", event_count: sequence });
  });
  ctx.on("ready", () => sample());
  ctx.effect(() => {
    const timer = setInterval(() => sample(), intervalMilliseconds);
    timer.unref?.();
    return async () => { clearInterval(timer); await sample("EXITING"); delete ctx[installed]; };
  });
}

export function apply(ctx) { startProbe(ctx); }
