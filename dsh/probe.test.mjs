import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collect, startProbe, intervalMilliseconds } from "./probe.mjs";

function fixture(records, archive = []) {
  const services = { sessionQuery: { listSessions: async () => records }, sessionPersistence: { list: async () => [] }, workspaceRegistry: { archivedSessionIds: archive }, agents: { get: (id) => id === "live" ? { session: { id }, status: "running" } : id === "stopped" ? { session: { id }, status: "completed" } : undefined } };
  return { get: (key) => services[key], on() {}, effect(fn) { this.dispose = fn(); } };
}
test("full native corpus keeps independently stopped and active objects and excludes native archive", async () => {
  const ctx = fixture(["live", "stopped", "stored", "archived"].map((id) => ({ header: { id }, live: id === "live", persisted: true })), ["archived"]);
  const result = await collect(ctx);
  assert.equal(result.coverage, "COMPLETE"); assert.equal(result.total, 3); assert.equal(result.archived, 1);
  assert.deepEqual(result.objects.map((o) => o.status), ["RUNNING", "COMPLETED", "UNKNOWN"]);
});
test("missing archive service and native listing failure are unknown", async () => {
  assert.equal((await collect({ get: () => undefined })).coverage, "UNKNOWN");
  const ctx = fixture([]); ctx.get("sessionQuery").listSessions = async () => { throw new Error("failure"); };
  assert.equal((await collect(ctx)).coverage, "UNKNOWN");
});
test("headless native JSON archive medium: missing means no marker; malformed never means empty", async () => {
  const root = await mkdtemp(join(tmpdir(), "slk-native-archive-"));
  const ctx = fixture(["live", "archived"].map((id) => ({ header: { id }, live: true, persisted: true })));
  const baseGet = ctx.get;
  ctx.get = (key) => key === "workspaceRegistry" ? undefined : key === "storage" ? { domain: { config: { backend: "json" } }, backend: { get: () => ({ root }) } } : baseGet(key);
  const absent = await collect(ctx); assert.equal(absent.coverage, "COMPLETE"); assert.equal(absent.total, 2); assert.match(absent.archive_source, /ABSENT/);
  const path = join(root, "workspace.json");
  await writeFile(path, JSON.stringify({ unit: { name: "workspace", version: 2 }, global: { archivedSessionIds: ["archived"] }, tables: {} }));
  const archived = await collect(ctx); assert.equal(archived.total, 1); assert.equal(archived.archived, 1); assert.equal(archived.archive_source, path);
  await writeFile(path, "broken"); assert.equal((await collect(ctx)).coverage, "UNKNOWN");
});
test("one timer per actual host, sixty seconds, no Run context dependency", async () => {
  const ctx = fixture([]); let count = 0; const original = ctx.effect; ctx.effect = (fn) => { count++; original.call(ctx, fn); };
  let samples = 0; startProbe(ctx, { ingest: async () => samples++ }); startProbe(ctx, { ingest: async () => samples++ });
  assert.equal(count, 1); assert.equal(intervalMilliseconds, 60_000); await ctx.dispose(); assert.equal(samples, 1);
});
