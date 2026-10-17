// @vitest-environment node
import { DatabaseSync } from "node:sqlite";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, it } from "vitest";
import { D1WebBiStore, type D1Database } from "./d1Store";
import { runFixture } from "../test/fixtures";
import { canonicalSummary, sha256, canonicalJson } from "../closeout";
import type { CloseoutSummary } from "../contracts";
import type { WebBiUploadEnvelope } from "./contracts";

it("persists actual per-Run receipts, monotonic summaries, sticky archive and two simulated devices", async () => {
  const directory = mkdtempSync(join(tmpdir(), "slk-webbi-"));
  const file = join(directory, "state.sqlite");
  let sqlite = new DatabaseSync(file);
  sqlite.exec(readFileSync(new URL("../../webbi/migrations/0001.sql", import.meta.url), "utf8"));
  sqlite.exec(readFileSync(new URL("../../webbi/migrations/0002_receipts.sql", import.meta.url), "utf8"));
  const db = { prepare(query: string) {
    const stmt = sqlite.prepare(query.replace(/\?\d+/g, "?"));
    let values: (string | number | null)[] = [];
    const args = () => [...query.matchAll(/\?(\d+)/g)].map((m) => values[Number(m[1]) - 1]!);
    return { bind(...v: typeof values) { values = v; return this; },
      async first() { return stmt.get(...args()) ?? null; },
      async all() { return { success: true, results: stmt.all(...args()) }; },
      async run() { return { success: true, results: [], meta: { changes: Number(stmt.run(...args()).changes) } }; } };
  }} as D1Database;
  const store = new D1WebBiStore(db, "unused");
  const summary = async (revision: number, body: string) => {
    const value: CloseoutSummary = { body, authored_by: "supervisor-a", recorded_at: "2026-10-18T00:00:00Z", source_id: `source-${revision}`, source_revision: revision, content_sha256: "" };
    value.content_sha256 = await sha256(canonicalSummary(value)); return value;
  };
  const one = await summary(1, "原文\n不修改 D2"); const two = await summary(2, "更正后的原文");
  const upload = (device: string, at: string, s?: CloseoutSummary, archived = false): WebBiUploadEnvelope => ({
    schema_version: "slk.bi.upload/v1", bi_version: "1.1.4", upload_id: `${device}-${at}`, generated_at: at,
    device: { device_id: device, device_name: device }, runs: [{ run: { ...structuredClone(runFixture),
      summary: { ...runFixture.summary, archived_at: archived ? "2026-10-18T01:00:00Z" : null },
      ...(s ? { closeout_summary: s, device_signature: { computer_name: device, ip_address: null, os_version: null } } : {}) }, messages: [] }],
  });
  try {
    await store.ingest(upload("A", "2026-10-18T01:00:00Z", one, true));
    await store.ingest(upload("B", "2026-10-18T01:00:00Z", one));
    const corrected = await store.ingest(upload("A", "2026-10-18T02:00:00Z", two));
    expect(corrected.receipts[0]?.source_revision).toBe(2);
    const old = await store.ingest(upload("A", "2026-10-18T03:00:00Z", one));
    expect(old.receipts[0]?.source_revision).toBe(2);
    const staleArchive = upload("A", "2026-10-18T03:30:00Z", one, true);
    staleArchive.runs[0]!.run.device_signature!.computer_name = "old-computer";
    staleArchive.runs[0]!.run.summary.run_name = "stale archive facts";
    const replay = await store.ingest(staleArchive);
    expect((await store.getRun("A", runFixture.run_id))!.run.device_signature?.computer_name).toBe("A");
    expect(replay.receipts[0]?.payload_sha256).toBe(old.receipts[0]?.payload_sha256);
    await store.ingest(upload("A", "2026-10-18T04:00:00Z"));
    const saved = (await store.getRun("A", runFixture.run_id))!;
    expect(saved.run.closeout_summary).toEqual(two);
    expect(saved.run.device_signature?.computer_name).toBe("A");
    expect(saved.run.summary.archived_at).toBe("2026-10-18T01:00:00Z");
    expect(old.receipts[0]?.payload_sha256).toBe(await sha256(canonicalJson(saved.run)));
    const conflict = await store.ingest(upload("A", "2026-10-18T05:00:00Z", await summary(2, "同版冲突"), true));
    expect(conflict.receipts[0]?.error).toBe("SLK_WEBBI_SUMMARY_REVISION_CONFLICT");
    expect((await store.getRun("B", runFixture.run_id))!.run.closeout_summary).toEqual(one);
    expect(await store.listRuns(true)).toHaveLength(1);
    expect(await store.listRuns(false)).toHaveLength(1);
    const badHash = await store.ingest(upload("A", "2026-10-18T06:00:00Z", { ...two, content_sha256: "0".repeat(64) }, true));
    expect(badHash.receipts[0]?.error).toBe("SLK_WEBBI_SUMMARY_HASH_INVALID");
    await Promise.all([
      store.ingest(upload("A", "2026-10-18T07:00:00Z", await summary(3, "第三版"), true)),
      store.ingest(upload("A", "2026-10-18T08:00:00Z", await summary(4, "第四版"), true)),
    ]);
    sqlite.close(); sqlite = new DatabaseSync(file);
    const reopened = new D1WebBiStore(db, "unused");
    expect((await reopened.getRun("A", runFixture.run_id))!.run.closeout_summary?.source_revision).toBe(4);
    expect((await reopened.getRun("B", runFixture.run_id))!.run.closeout_summary?.source_revision).toBe(1);
  } finally {
    sqlite.close();
    if (!resolve(directory).startsWith(resolve(tmpdir()) + "/") && !resolve(directory).startsWith(resolve(tmpdir()) + "\\")) throw new Error("test cleanup escaped temporary root");
    rmSync(directory, { recursive: true, force: true });
  }
});
