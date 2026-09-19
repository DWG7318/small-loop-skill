import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SlkApi } from "./api";
import { twoRunFixture } from "./test/fixtures";
import { useSlkData } from "./useSlkData";

describe("useSlkData", () => {
  it("keeps the last good snapshot when refresh fails", async () => {
    let refresh = 0;
    const api = {
      projects: async () => {
        if (refresh++ > 0) throw new Error("database busy");
        return twoRunFixture.projects;
      },
      runs: async () => twoRunFixture.runs,
    } as SlkApi;

    const { result } = renderHook(() => useSlkData(api));
    await waitFor(() => expect(result.current.snapshot).toEqual(twoRunFixture));

    await act(async () => result.current.refresh());
    expect(result.current.snapshot).toEqual(twoRunFixture);
    expect(result.current.staleReason).toBe("database busy");
  });
});
