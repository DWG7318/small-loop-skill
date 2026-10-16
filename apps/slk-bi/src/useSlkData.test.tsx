import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SlkApi } from "./api";
import { twoRunFixture } from "./test/fixtures";
import { useSlkData } from "./useSlkData";

describe("useSlkData", () => {
  it("keeps readable Runs when one source cannot be read", async () => {
    const healthy = twoRunFixture.runDetails[0]!;
    const api = {
      metadata: async () => ({ schema_version: "slk.bi.metadata/v1", bi_version: "1.1.4", device_id: "pc", device_name: "PC", webbi_sync_enabled: false }),
      projects: async () => twoRunFixture.projects,
      runs: async () => twoRunFixture.runs,
      run: async (id: string) => { if (id !== healthy.run_id) throw new Error("source unavailable"); return healthy; },
    } as SlkApi;
    const { result } = renderHook(() => useSlkData(api));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshot?.runDetails).toEqual([healthy]);
    expect(result.current.staleReason).toContain("source unavailable");
  });
  it("keeps the last good snapshot when refresh fails", async () => {
    let refresh = 0;
    const metadata = {
      schema_version: "slk.bi.metadata/v1" as const,
      bi_version: "1.1.0" as const,
      device_id: "device-a",
      device_name: "Workstation A",
      webbi_sync_enabled: false,
    };
    const api = {
      metadata: async () => metadata,
      projects: async () => {
        if (refresh++ > 0) throw new Error("database busy");
        return twoRunFixture.projects;
      },
      runs: async () => twoRunFixture.runs,
      run: async (runId: string) => twoRunFixture.runDetails.find((run) => run.run_id === runId)!,
    } as SlkApi;
    const expected = { metadata, ...twoRunFixture };

    const { result } = renderHook(() => useSlkData(api));
    await waitFor(() => expect(result.current.snapshot).toEqual(expected));

    await act(async () => result.current.refresh());
    expect(result.current.snapshot).toEqual(expected);
    expect(result.current.staleReason).toBe("database busy");
  });
});
