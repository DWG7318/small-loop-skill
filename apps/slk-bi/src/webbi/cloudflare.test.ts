// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import worker from "./cloudflare";

function environment() {
  const write = vi.fn(async () => { throw new Error("unexpected database write"); });
  return {
    DB: {
      prepare: () => ({
        bind() { return this; },
        all: async () => ({ results: [], success: true }),
        first: async () => null,
        run: write,
      }),
    },
    ASSETS: { fetch: async () => new Response("WebBI assets") },
    WEBBI_ADMIN_TOKEN: "admin-test-secret",
    WEBBI_INGEST_TOKEN: "ingest-test-secret",
    WEBBI_SETTINGS_ENCRYPTION_KEY: "unused-for-read",
  };
}

describe("WebBI public reading / protected writing", () => {
  it.each([
    "/api/v1/runs?archive=active", "/api/v1/runs?archive=archived",
    "/api/v1/catalog", "/api/v1/notification-settings",
  ])("reads %s without a login, cookie or bearer", async (path) => {
    const response = await worker.fetch(new Request(`https://slk.example.test${path}`), environment());
    expect(response.status).toBe(200);
    const body = await response.text();
    expect(body).not.toContain("admin-test-secret");
    expect(body).not.toContain("ingest-test-secret");
    expect(body).not.toContain("encrypted_secret");
    expect(body).not.toContain("secret_iv");
  });

  it("returns a real anonymous detail lookup, not an authentication failure", async () => {
    const response = await worker.fetch(new Request("https://slk.example.test/api/v1/runs/device/missing"), environment());
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "SLK_WEBBI_RUN_NOT_FOUND" });
  });

  it.each([
    {},
    { "cf-access-authenticated-user-email": "owner@example.test" },
    { "cf-access-jwt-assertion": "caller-supplied-token" },
    { authorization: "Bearer ingest-test-secret" },
  ])("does not grant settings/test writes from public viewing or an unrelated credential: %o", async (headers) => {
    for (const [path, method] of [
      ["/api/v1/notification-settings", "PUT"],
      ["/api/v1/notification-settings/test", "POST"],
    ]) {
      const response = await worker.fetch(new Request(`https://slk.example.test${path}`, {
        method, headers: headers as HeadersInit, body: "{}",
      }), environment());
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: "SLK_WEBBI_ADMIN_UNAUTHORIZED" });
    }
  });

  it("keeps the upload credential separate from admin authorization", async () => {
    for (const headers of [{}, { authorization: "Bearer admin-test-secret" }]) {
      const response = await worker.fetch(new Request("https://slk.example.test/api/v1/uploads", {
        method: "POST", headers: headers as HeadersInit, body: "{}",
      }), environment());
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: "SLK_WEBBI_UPLOAD_UNAUTHORIZED" });
    }
  });

  it("does not use the read exemption for another method or route", async () => {
    for (const [path, method] of [
      ["/api/v1/runs", "PUT"], ["/api/v1/catalog", "POST"],
      ["/api/v1/notification-settings/test", "GET"], ["/api/v1/unknown", "GET"],
    ]) {
      const response = await worker.fetch(new Request(`https://slk.example.test${path}`, { method }), environment());
      expect(response.status).toBe(404);
    }
  });

  it("serves browser assets without requiring an identity provider", async () => {
    const response = await worker.fetch(new Request("https://slk.example.test/"), environment());
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("WebBI assets");
  });
});
