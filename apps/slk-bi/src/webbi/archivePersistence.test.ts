// @vitest-environment node
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { D1WebBiStore, type D1Database } from "./d1Store";
import { runFixture } from "../test/fixtures";
import { BI_VERSION } from "../version";

describe("persistent WebBI archival", () => {
  it("never resurrects an archived Run via older snapshots or a newly retried envelope", async () => {
    const sqlite = new DatabaseSync(":memory:");
    try {
      sqlite.exec(readFileSync(new URL("../../webbi/migrations/0001.sql", import.meta.url), "utf8"));
      sqlite.exec(readFileSync(new URL("../../webbi/migrations/0002_receipts.sql", import.meta.url), "utf8"));
      const database = { prepare(query: string) {
        const stmt = sqlite.prepare(query);
        let params: (string | number | null)[] = [];
        // D1 uses ?1; Node SQLite requires named binding or anonymous placeholders.
        const portable = sqlite.prepare(query.replace(/\?\d+/g, "?"));
        void stmt;
        return {
          bind(...values: (string | number | null)[]) { params = values; return this; },
          async run() {
            // Repeated numbered placeholders must reuse the same positional value.
            const order = [...query.matchAll(/\?(\d+)/g)].map((m) => params[Number(m[1]) - 1]!);
            const result = portable.run(...order);
            return {success: true, results: [], meta: {changes: Number(result.changes)}};
          },
          async first() {return portable.get(...params) ?? null;},
          async all() {return {success: true, results: portable.all(...params)};},
        };
      }} as unknown as D1Database;
      const store = new D1WebBiStore(database,"unused");
      const run = structuredClone(runFixture);
      const envelope = (device: string, at: string, archive: boolean) => ({
        schema_version: "slk.bi.upload/v1" as const, bi_version: BI_VERSION, upload_id: `${device}-${at}`,
        generated_at: at, device: {device_id: device, device_name: device},
        runs: [{run: {...run, summary: {...run.summary, archived_at: archive ? at : null}}, messages: []}],
      });
      await store.ingest(envelope("A","2026-10-16T01:00:00Z",false));
      await store.ingest(envelope("A","2026-10-16T02:00:00Z",true));
      await store.ingest(envelope("A","2026-10-16T01:30:00Z",false));
      await store.ingest(envelope("A","2026-10-16T03:00:00Z",false));
      await store.ingest(envelope("B","2026-10-16T03:00:00Z",false));
      expect((await store.getRun("A", run.run_id))?.run.summary.archived_at).toBe("2026-10-16T02:00:00Z");
      expect((await store.getRun("B", run.run_id))?.run.summary.archived_at).toBeNull();
      expect(await store.listRuns(true)).toHaveLength(1);
      expect(await store.listRuns(false)).toHaveLength(1);
    } finally {sqlite.close();}
  });
});
