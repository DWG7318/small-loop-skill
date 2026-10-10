import { afterEach, describe, expect, it, vi } from "vitest";

import { webBiApi } from "./webApi";

afterEach(() => vi.unstubAllGlobals());

describe("WebBI browser authorization", () => {
  it.each(["1.1.0", "1.1.1"])("reads %s without attaching a viewing credential or requiring a login", async (bi_version) => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({
      schema_version: "slk.webbi.runs/v1", bi_version, runs: [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    await webBiApi.listRuns(false);
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("authorization")).toBeNull();
  });

  it("saves and tests manual settings without an authorization header or stored credential", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({ status: "sent" }));
    vi.stubGlobal("fetch", fetchMock);
    await webBiApi.saveNotificationSettings({
      enabled: false, server_url: "https://ntfy.example.test", topic: "slk",
      auth_mode: "none", selection_mode: "all", selected_message_types: [],
    });
    await webBiApi.testNotification();
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("authorization")).toBeNull();
      expect(new Headers(init?.headers).get("cookie")).toBeNull();
    }
    expect(window.localStorage.length).toBe(0);
  });
});
