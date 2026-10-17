import { expect, it } from "vitest";
import { deviceSignatureLabel, canonicalSummary } from "./closeout";
import { parseRunProjection } from "./contracts";
import { runFixture } from "./test/fixtures";

it("does not probe or invent missing device facts", () => {
  expect(deviceSignatureLabel()).toBe("未获取 · 未获取 · 未获取");
  expect(deviceSignatureLabel({ computer_name: "PC-A", ip_address: null, os_version: "Windows 11" })).toBe("PC-A · 未获取 · Windows 11");
});
it("uses the shared fixed key order without altering original Unicode text", () => {
  expect(canonicalSummary({ body: "原文\n", authored_by: "a", recorded_at: "t", source_id: "s", source_revision: 2, content_sha256: "ignored" })).toBe('{"body":"原文\\n","authored_by":"a","recorded_at":"t","source_id":"s","source_revision":2}');
});
it("keeps legacy projections readable and rejects arbitrary optional metadata", () => {
  expect(parseRunProjection(runFixture)).toEqual(runFixture);
  expect(() => parseRunProjection({ ...runFixture, device_signature: { computer_name: null, ip_address: null, os_version: null, token: "no" } })).toThrow();
  expect(() => parseRunProjection({ ...runFixture, closeout_summary: { body: "no" } })).toThrow();
  const summary = { body: "原文".repeat(100_000), authored_by: "supervisor-a", recorded_at: "2026-10-18T00:00:00Z", source_id: "s", source_revision: 1, content_sha256: "0".repeat(64) };
  expect(parseRunProjection({ ...runFixture, closeout_summary: summary }).closeout_summary?.body).toBe(summary.body);
});
