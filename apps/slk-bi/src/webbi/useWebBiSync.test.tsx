import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useWebBiSync } from "./useWebBiSync";
import { fixtureApi, twoRunFixture } from "../test/fixtures";

it("shows failures and serializes attempts without inventing formal messages", async () => {
  const syncWebBi = vi.fn().mockRejectedValue(new Error("SLK_WEBBI_UPLOAD_FAILED"));
  const api = { ...fixtureApi, syncWebBi };
  const snapshot = { ...twoRunFixture, metadata: { ...await fixtureApi.metadata(), webbi_sync_enabled: true } };
  const { result, unmount } = renderHook(() => useWebBiSync(api, snapshot));
  await waitFor(() => expect(result.current.status).toBe("failed"));
  expect(result.current.error).toContain("SLK_WEBBI_UPLOAD_FAILED");
  expect(syncWebBi).toHaveBeenCalledTimes(1); unmount();
});

it("persists through the host even when cloud settings are missing", async () => {
  const syncWebBi = vi.fn().mockResolvedValue({ status: "disabled", upload_id: null, runs: [] });
  const api = { ...fixtureApi, syncWebBi }; const snapshot = { ...twoRunFixture, metadata: await fixtureApi.metadata() };
  const { result, unmount } = renderHook(() => useWebBiSync(api, snapshot));
  await act(async () => { await Promise.resolve(); });
  await waitFor(() => expect(syncWebBi).toHaveBeenCalledOnce());
  expect(result.current.status).toBe("disabled"); unmount();
});

it("invalidates an old saved receipt immediately when a Run changes or a new Run appears", async () => {
  const api = { ...fixtureApi, syncWebBi: vi.fn().mockResolvedValue({ status: "uploaded", upload_id: "first", runs: ["run-a", "run-b"].map((run_id) => ({ run_id, status: "uploaded", receipt: { saved_at: "old" } })) }) };
  const initial = { ...twoRunFixture, metadata: { ...await fixtureApi.metadata(), webbi_sync_enabled: true } };
  const { result, rerender, unmount } = renderHook(({ snapshot }) => useWebBiSync(api, snapshot), { initialProps: { snapshot: initial } });
  await waitFor(() => expect(result.current.status).toBe("uploaded"));
  const changed = { ...initial, runDetails: initial.runDetails.map((run) => run.run_id === "run-a" ? { ...run, summary: { ...run.summary, run_name: "Updated work in progress" } } : run) };
  rerender({ snapshot: changed });
  expect(result.current.status).toBe("pending");
  expect(result.current.runs?.find((run) => run.run_id === "run-a")?.receipt).toBeUndefined();
  expect(result.current.runs?.find((run) => run.run_id === "run-b")?.status).toBe("uploaded");
  expect(api.syncWebBi).toHaveBeenCalledTimes(1);
  const newRun = { ...initial.runDetails[0]!, run_id: "run-new", summary: { ...initial.runDetails[0]!.summary, run_id: "run-new" } };
  rerender({ snapshot: { ...changed, runs: { ...changed.runs, runs: [...changed.runs.runs, newRun.summary] }, runDetails: [...changed.runDetails, newRun] } });
  expect(result.current.runs?.find((run) => run.run_id === "run-new")).toEqual({ run_id: "run-new", status: "pending" });
  const before = api.syncWebBi.mock.calls.length;
  rerender({ snapshot: { ...changed } });
  expect(api.syncWebBi.mock.calls.length).toBe(before);
  unmount();
});

it("queues only the latest formal change behind an in-flight upload and rejects its old receipt", async () => {
  let finishFirst: (value: unknown) => void = () => undefined;
  let finishLatest: (value: unknown) => void = () => undefined;
  const syncWebBi = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve; }))
    .mockImplementation(() => new Promise((resolve) => { finishLatest = resolve; }));
  const api = { ...fixtureApi, syncWebBi };
  const initial = { ...twoRunFixture, metadata: { ...await fixtureApi.metadata(), webbi_sync_enabled: true } };
  const { result, rerender, unmount } = renderHook(({ snapshot }) => useWebBiSync(api, snapshot), { initialProps: { snapshot: initial } });
  const archived = { ...initial, runDetails: initial.runDetails.map((run) => run.run_id === "run-a" ? { ...run, summary: { ...run.summary, archived_at: "2026-10-18T00:00:00Z" } } : run) };
  rerender({ snapshot: archived });
  const corrected = { ...archived, runDetails: archived.runDetails.map((run) => run.run_id === "run-a" ? { ...run, closeout_summary: { body: "Original formal correction", authored_by: "creator", recorded_at: "2026-10-18T00:01:00Z", source_id: "source-2", source_revision: 2, content_sha256: "b".repeat(64) } } : run) };
  rerender({ snapshot: corrected });
  expect(syncWebBi).toHaveBeenCalledTimes(1);
  await act(async () => { finishFirst({ status: "uploaded", upload_id: "old", runs: ["run-a", "run-b"].map((run_id) => ({ run_id, status: "uploaded", receipt: { saved_at: "old" } })) }); });
  expect(result.current.runs?.find((run) => run.run_id === "run-a")?.status).toBe("pending");
  expect(result.current.runs?.find((run) => run.run_id === "run-a")?.receipt).toBeUndefined();
  expect(syncWebBi).toHaveBeenCalledTimes(2);
  expect(syncWebBi.mock.calls[1]![0].runs.find((item: { run: { run_id: string } }) => item.run.run_id === "run-a").run.closeout_summary.source_revision).toBe(2);
  await act(async () => { finishLatest({ status: "uploaded", upload_id: "latest", runs: ["run-a", "run-b"].map((run_id) => ({ run_id, status: "uploaded", receipt: { saved_at: "latest" } })) }); });
  expect(result.current.status).toBe("uploaded");
  rerender({ snapshot: { ...corrected } });
  expect(syncWebBi).toHaveBeenCalledTimes(2);
  unmount();
});

it("invalidates destination receipts and attempts again after a settings save", async () => {
  const syncWebBi = vi.fn().mockResolvedValueOnce({ status: "uploaded", upload_id: "old-destination", runs: ["run-a", "run-b"].map((run_id) => ({ run_id, status: "uploaded", receipt: { saved_at: "old" } })) })
    .mockImplementation(() => new Promise(() => undefined));
  const api = { ...fixtureApi, syncWebBi };
  const snapshot = { ...twoRunFixture, metadata: { ...await fixtureApi.metadata(), webbi_sync_enabled: true } };
  const { result, rerender, unmount } = renderHook(({ settingsRevision }) => useWebBiSync(api, snapshot, settingsRevision), { initialProps: { settingsRevision: 0 } });
  await waitFor(() => expect(result.current.status).toBe("uploaded"));
  rerender({ settingsRevision: 1 });
  expect(result.current.status).toBe("pending");
  expect(result.current.runs?.every((run) => run.receipt === undefined)).toBe(true);
  expect(syncWebBi).toHaveBeenCalledTimes(2);
  unmount();
});

it("actively uploads legacy closure-based archive transitions without a new summary", async () => {
  const syncWebBi = vi.fn().mockResolvedValue({ status: "uploaded", upload_id: "saved", runs: ["run-a", "run-b"].map((run_id) => ({ run_id, status: "uploaded" })) });
  const api = { ...fixtureApi, syncWebBi };
  const initial = { ...twoRunFixture, metadata: { ...await fixtureApi.metadata(), webbi_sync_enabled: true } };
  const { rerender, unmount } = renderHook(({ snapshot }) => useWebBiSync(api, snapshot), { initialProps: { snapshot: initial } });
  await act(async () => { await Promise.resolve(); });
  const archived = { ...initial, runDetails: initial.runDetails.map((run) => run.run_id === "run-a" ? { ...run, summary: { ...run.summary, closure_state: "closed" } } : run) };
  rerender({ snapshot: archived });
  await act(async () => { await Promise.resolve(); });
  expect(syncWebBi).toHaveBeenCalledTimes(2);
  unmount();
});
