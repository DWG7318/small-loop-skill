import { afterEach, describe, expect, it, vi } from "vitest";

import { runFixture } from "../test/fixtures";
import type { IngestedMessage, NtfyDeliveryTarget } from "./worker";
import { NtfyNotifier } from "./ntfy";

afterEach(() => vi.unstubAllGlobals());

describe("ntfy delivery", () => {
  it("sends the exact Agent-authored label and scope without exposing config secrets", async () => {
    const fetchMock = vi.fn<(
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => Promise<Response>>(async () => new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const target: NtfyDeliveryTarget = {
      settings: {
        enabled: true,
        server_url: "https://ntfy.example.test",
        topic: "slk-owner",
        auth_mode: "token",
        username: null,
        encrypted_secret: "ciphertext-not-sent",
        secret_iv: "iv-not-sent",
        selection_mode: "all",
        selected_message_types: [],
        config_version: 3,
      },
      secret: "runtime-token",
    };
    const record: IngestedMessage = {
      device: { device_id: "device-a", device_name: "Workstation A" },
      run: runFixture,
      message: {
        message_id: "EVENT:d1-failed",
        run_id: "run-a",
        source_kind: "EVENT",
        source_id: "d1-failed",
        message_type: "D1_FAILED",
        label_zh: "D1 未通过",
        author_role: "checker",
        author_identity_ref: "checker-a",
        go_id: "GO-001",
        cell_id: "CELL-001",
        attempt: 2,
        occurred_at: "2026-10-04T00:00:00Z",
      },
    };

    await new NtfyNotifier().send(target, record);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("https://ntfy.example.test/slk-owner");
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer runtime-token");
    expect(init?.body).toContain("D1 未通过");
    expect(init?.body).toContain("checker · GO-001 · CELL-001");
    expect(init?.body).not.toContain("ciphertext-not-sent");
  });
});
