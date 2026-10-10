import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { fixtureApi, runFixture } from "./test/fixtures";

const native = vi.hoisted(() => ({
  monitor: vi.fn(), innerSize: vi.fn(), outerSize: vi.fn(), outerPosition: vi.fn(), setSize: vi.fn(), setPosition: vi.fn(),
  onMoved: vi.fn(), onScaleChanged: vi.fn(),
}));
vi.mock("@tauri-apps/api/window", () => ({
  currentMonitor: native.monitor,
  getCurrentWindow: () => native,
}));

let scale: number;
let verticalFrame: number;
let stateNaturalHeight: number;
let position: { x: number; y: number };
let size: { width: number; height: number };
const resizeCallbacks = new Set<ResizeObserverCallback>();

// Deterministic geometry tests the sizing controller, not browser layout or native DPI.
function height(element: Element | null): number {
  if (!element) return 0;
  const nodes = (selector: string) => Array.from(element.querySelectorAll(selector));
  const limited = (natural: number, value: string) => Math.min(natural, Number.parseFloat(value) || Infinity);
  if (element.matches(".slk-row")) return 68;
  if (element.matches(".cell-row")) return 43;
  if (element.matches(".role-strip")) return 59;
  if (element.matches(".overwatch-status")) return 28;
  if (element.matches(".cell-list")) return limited(element.children.length * 43, (element as HTMLElement).style.maxHeight || "258");
  if (element.matches(".run-details")) return 1 + height(element.querySelector(".role-strip")) + height(element.querySelector(".overwatch-status")) + height(element.querySelector(".cell-list"));
  if (element.matches(".slk-block")) return 69 + height(element.querySelector(".run-details"));
  if (element.matches(".runs-content")) return nodes(".slk-block").reduce((total, block) => total + height(block), 0) + (element.querySelector(".archive-panel") ? 32 : 0);
  if (element.matches(".runs-surface")) return limited(height(element.querySelector(".runs-content")), (element as HTMLElement).style.height);
  if (element.matches(".control-bar")) return 31;
  if (element.matches(".app-state")) return limited(stateNaturalHeight, (element as HTMLElement).style.maxHeight);
  if (element.matches(".app-shell")) return Math.max(94, 33 + height(element.querySelector(".runs-surface, .app-state")));
  return 0;
}

function apiWithCells(count: number, runs = 1) {
  const summaries = Array.from({ length: runs }, (_, index) => ({ ...runFixture.summary, run_id: `run-${index}`, run_name: `Run ${index}` }));
  return {
    ...fixtureApi,
    runs: async () => ({ schema_version: "slk.bi.runs/v1" as const, runs: summaries }),
    run: async (runId: string) => ({
      ...runFixture, run_id: runId, summary: summaries.find((summary) => summary.run_id === runId)!,
      go_nodes: [{ ...runFixture.go_nodes[0]!, cell_nodes: Array.from({ length: count }, (_, index) => ({
        ...runFixture.go_nodes[0]!.cell_nodes[0]!, cell_id: `cell-${index}`, ordinal: index + 1, title: `Cell ${index + 1}`,
      })) }],
    }),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  scale = 1;
  verticalFrame = 0;
  stateNaturalHeight = 112;
  position = { x: 40, y: 100 };
  size = { width: 800, height: 300 };
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
  native.monitor.mockImplementation(async () => ({ scaleFactor: scale, workArea: { position: { x: 0, y: 0 }, size: { width: 1920, height: 1000 } } }));
  native.innerSize.mockImplementation(async () => size);
  native.outerSize.mockImplementation(async () => ({ width: size.width + verticalFrame, height: size.height + verticalFrame }));
  native.outerPosition.mockImplementation(async () => position);
  native.setSize.mockImplementation(async (next) => { size = { width: next.width, height: next.height }; });
  native.setPosition.mockImplementation(async (next) => { position = { x: next.x, y: next.y }; });
  native.onMoved.mockResolvedValue(vi.fn());
  native.onScaleChanged.mockResolvedValue(vi.fn());
  vi.stubGlobal("ResizeObserver", class {
    callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) { this.callback = callback; resizeCallbacks.add(callback); }
    observe() {}
    unobserve() {}
    disconnect() { resizeCallbacks.delete(this.callback); }
  });
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    return { x: 0, y: 0, top: 0, left: 0, right: 800, bottom: height(this), width: 800, height: height(this), toJSON() {} } as DOMRect;
  });
  const original = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) => {
    const style = original(element);
    return new Proxy(style, { get(target, key) {
      if (key === "borderTopWidth" && element.matches(".app-shell")) return "1px";
      if (key === "borderBottomWidth" && element.matches(".app-shell, .slk-block")) return "1px";
      const value = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    } });
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

describe("intrinsic desktop sizing", () => {
  const framedCases = [{ dpi: 1, frame: 8 }, { dpi: 1.25, frame: 11 }, { dpi: 1.5, frame: 13 }];

  it("shrinks directly to the complete border box and preserves width without repositioning", async () => {
    const user = userEvent.setup();
    render(<App api={apiWithCells(16)} />);
    await user.click(await screen.findByRole("button", { name: "展开 Run 0" }));
    await waitFor(() => expect(size.height).toBe(420));
    native.setSize.mockClear();
    await user.click(screen.getByRole("button", { name: "收起 Run 0" }));
    await waitFor(() => expect(size).toEqual({ width: 800, height: 102 }));
    expect(native.setSize).toHaveBeenCalledTimes(1);
    expect(native.setPosition).not.toHaveBeenCalled();
    await act(async () => { for (const callback of resizeCallbacks) callback([], {} as ResizeObserver); });
    expect(native.setSize).toHaveBeenCalledTimes(1);
  });

  it.each([1, 1.25, 1.5])("uses physical workArea and position consistently at scale %s", async (dpi) => {
    scale = dpi;
    size.width = 720 * dpi;
    position.y = 550;
    const user = userEvent.setup();
    render(<App api={apiWithCells(16, 6)} />);
    await user.click(await screen.findByRole("button", { name: "展开 Run 0" }));
    await waitFor(() => expect(size.height).toBeLessThanOrEqual(450));
    expect(size.width).toBe(720 * dpi);
    expect(native.setPosition).not.toHaveBeenCalled();
    const list = screen.getByRole("list", { name: "Run 0 CELL 记录" });
    expect(Number.parseFloat(list.style.maxHeight)).toBeLessThan(258);
    expect(list.children).toHaveLength(16);
  });

  it.each([1, 1.25, 1.5])("moves upward only enough to fit the 94px minimum at scale %s", async (dpi) => {
    scale = dpi;
    position.y = 980;
    size.width = 720 * dpi;
    render(<App api={apiWithCells(1)} />);
    await waitFor(() => expect(native.setPosition).toHaveBeenCalledTimes(1));
    expect(native.setPosition.mock.calls[0]![0]).toMatchObject({ x: 40, y: 1000 - Math.ceil(94 * dpi) });
    await waitFor(() => expect(position.y + size.height).toBeLessThanOrEqual(1000));
    expect(size.width).toBe(720 * dpi);
  });

  it.each(framedCases)("subtracts the measured $frame physical frame at scale $dpi without repositioning", async ({ dpi, frame }) => {
    scale = dpi;
    verticalFrame = frame;
    position.y = 550;
    size.width = 720 * dpi;
    const user = userEvent.setup();
    render(<App api={apiWithCells(16, 6)} />);
    await user.click(await screen.findByRole("button", { name: "展开 Run 0" }));
    const clientBudget = 450 - frame;
    await waitFor(() => expect(size.height).toBe(Math.ceil(Math.floor(clientBudget / dpi) * dpi)));
    expect(position.y + size.height + frame).toBeLessThanOrEqual(1000);
    expect(size.width).toBe(720 * dpi);
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it.each(framedCases)("includes the actual $frame frame in the minimum upward move at scale $dpi", async ({ dpi, frame }) => {
    scale = dpi;
    verticalFrame = frame;
    position.y = 980;
    size.width = 720 * dpi;
    render(<App api={apiWithCells(1)} />);
    const clientMinimum = Math.ceil(94 * dpi);
    await waitFor(() => expect(native.setPosition).toHaveBeenCalledTimes(1));
    expect(native.setPosition.mock.calls[0]![0]).toMatchObject({ x: 40, y: 1000 - clientMinimum - frame });
    await waitFor(() => expect(size.height).toBe(clientMinimum));
    expect(position.y + size.height + frame).toBe(1000);
    expect(size.width).toBe(720 * dpi);
  });

  it.each(framedCases)("does not move when the framed minimum fits exactly at scale $dpi", async ({ dpi, frame }) => {
    scale = dpi;
    verticalFrame = frame;
    const clientMinimum = Math.ceil(94 * dpi);
    position.y = 1000 - clientMinimum - frame;
    render(<App api={apiWithCells(1)} />);
    await screen.findByRole("button", { name: "展开 Run 0" });
    await waitFor(() => expect(size.height).toBe(clientMinimum));
    expect(position.y + size.height + frame).toBe(1000);
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it.each(framedCases)("rejects a workArea one physical pixel below the framed minimum at scale $dpi", async ({ dpi, frame }) => {
    scale = dpi;
    verticalFrame = frame;
    const minimum = Math.ceil(94 * dpi) + frame;
    native.monitor.mockResolvedValue({ scaleFactor: dpi, workArea: {
      position: { x: -1920, y: -1000 }, size: { width: 1920, height: minimum - 1 },
    } });
    position = { x: -1700, y: -1000 };
    render(<App api={apiWithCells(1)} />);
    expect(await screen.findByTitle(/工作区小于窗口必要最小高度/)).toBeVisible();
    expect(native.setSize).not.toHaveBeenCalled();
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it("does not apply a stale asynchronous measurement after a quick disclosure switch", async () => {
    const user = userEvent.setup();
    render(<App api={apiWithCells(16)} />);
    await screen.findByRole("button", { name: "展开 Run 0" });
    await waitFor(() => expect(size.height).toBe(102));
    let release!: (value: unknown) => void;
    native.monitor.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    await user.click(screen.getByRole("button", { name: "展开 Run 0" }));
    await user.click(screen.getByRole("button", { name: "收起 Run 0" }));
    native.setSize.mockClear();
    await act(async () => release(await native.monitor()));
    await waitFor(() => expect(size.height).toBe(102));
    expect(native.setSize).not.toHaveBeenCalled();
  });

  it("respects a nonzero workArea origin without moving to a different monitor", async () => {
    scale = 1.25;
    position = { x: -1700, y: -300 };
    size.width = 900;
    native.monitor.mockResolvedValue({ scaleFactor: scale, workArea: {
      position: { x: -1920, y: -1000 }, size: { width: 1920, height: 900 },
    } });
    const user = userEvent.setup();
    render(<App api={apiWithCells(16, 6)} />);
    await user.click(await screen.findByRole("button", { name: "展开 Run 0" }));
    await waitFor(() => expect(size).toEqual({ width: 900, height: 200 }));
    expect(position).toEqual({ x: -1700, y: -300 });
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it("cleans up native listeners and rejects callbacks after unmount", async () => {
    const stopMoved = vi.fn();
    const stopScale = vi.fn();
    native.onMoved.mockResolvedValue(stopMoved);
    native.onScaleChanged.mockResolvedValue(stopScale);
    const { unmount } = render(<App api={apiWithCells(1)} />);
    await screen.findByRole("button", { name: "展开 Run 0" });
    await waitFor(() => expect(native.onScaleChanged).toHaveBeenCalledTimes(1));
    unmount();
    expect(stopMoved).toHaveBeenCalledTimes(1);
    expect(stopScale).toHaveBeenCalledTimes(1);
    native.monitor.mockClear();
    native.onMoved.mock.calls[0]![0]();
    native.onScaleChanged.mock.calls[0]![0]();
    expect(native.monitor).not.toHaveBeenCalled();
  });

  it.each(["error", "unconfigured"])("makes a frame-constrained %s state keyboard-scrollable without changing Run quotas", async (kind) => {
    verticalFrame = 8;
    stateNaturalHeight = 152.59375;
    position.y = 1010;
    native.monitor.mockResolvedValue({ scaleFactor: 1, workArea: {
      position: { x: 0, y: 0 }, size: { width: 1920, height: 1040 },
    } });
    const api = { ...fixtureApi, metadata: async () => { throw new Error(kind === "error" ? "backend offline" : "No such file: missing state root"); } };
    render(<App api={api} />);
    const retry = await screen.findByRole("button", { name: "Retry read" });
    const state = retry.closest<HTMLElement>(".app-state")!;
    await waitFor(() => expect(state.style.maxHeight).toBe("61px"));
    expect(state.style.minHeight).toBe("0px");
    expect(state.style.overflowY).toBe("auto");
    expect(state).toHaveAttribute("tabindex", "0");
    state.focus();
    expect(state).toHaveFocus();
    expect(screen.queryByRole("list", { name: /CELL 记录/ })).not.toBeInTheDocument();
    await waitFor(() => expect(size.height).toBe(94));
    expect(position.y + size.height + verticalFrame).toBe(1040);
    expect(native.setPosition).toHaveBeenCalledTimes(1);
  });

  it("restores the natural AppState height when sufficient workArea becomes available", async () => {
    verticalFrame = 8;
    stateNaturalHeight = 152.59375;
    position.y = 980;
    const api = { ...fixtureApi, metadata: async () => { throw new Error("backend offline"); } };
    render(<App api={api} />);
    const state = (await screen.findByRole("button", { name: "Retry read" })).closest<HTMLElement>(".app-state")!;
    await waitFor(() => expect(state.style.maxHeight).toBe("61px"));
    position.y = 100;
    await act(async () => native.onMoved.mock.calls[0]![0]());
    await waitFor(() => expect(size.height).toBe(186));
    expect(state.style.maxHeight).toBe("");
    expect(state.style.minHeight).toBe("");
    expect(state.style.overflowY).toBe("");
  });

  it("keeps direct Run collapse unchanged with a measured 8px native frame", async () => {
    verticalFrame = 8;
    position.y = 550;
    const user = userEvent.setup();
    render(<App api={apiWithCells(16)} />);
    await user.click(await screen.findByRole("button", { name: "展开 Run 0" }));
    await waitFor(() => expect(size.height).toBe(420));
    native.setSize.mockClear();
    await user.click(screen.getByRole("button", { name: "收起 Run 0" }));
    await waitFor(() => expect(size).toEqual({ width: 800, height: 102 }));
    expect(native.setSize).toHaveBeenCalledTimes(1);
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it("keeps an unconstrained AppState intrinsic height and existing styles unchanged", async () => {
    stateNaturalHeight = 152.59375;
    const api = { ...fixtureApi, metadata: async () => { throw new Error("backend offline"); } };
    render(<App api={api} />);
    const state = (await screen.findByRole("button", { name: "Retry read" })).closest<HTMLElement>(".app-state")!;
    await waitFor(() => expect(size.height).toBe(186));
    expect(state.style.maxHeight).toBe("");
    expect(state.style.minHeight).toBe("");
    expect(state.style.overflowY).toBe("");
    expect(native.setPosition).not.toHaveBeenCalled();
  });

  it("contains native sizing errors and keeps the read-only surface visible", async () => {
    native.setSize.mockRejectedValue(new Error("resize denied"));
    render(<App api={apiWithCells(1)} />);
    expect(await screen.findByTitle(/resize denied/)).toBeVisible();
    expect(screen.getByRole("main", { name: "SLK Runs" })).toBeVisible();
  });
});
