import { afterEach, describe, expect, it, vi } from "vitest";

import { webBiApi } from "./webApi";

afterEach(() => vi.unstubAllGlobals());

describe("WebBI browser authorization", () => {
  it("does not attach a viewing credential or require a login", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({
      schema_version: "slk.webbi.runs/v1", bi_version: "1.1.0", runs: [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    await webBiApi.listRuns(false);
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("authorization")).toBeNull();
  });

  it("sends the supplied management token only with the write, without retaining it", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({ status: "sent" }));
    vi.stubGlobal("fetch", fetchMock);
    await webBiApi.testNotification("admin-edit-secret");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("authorization")).toBe("Bearer admin-edit-secret");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("cookie")).toBeNull();
    expect(window.localStorage.length).toBe(0);
  });
});
