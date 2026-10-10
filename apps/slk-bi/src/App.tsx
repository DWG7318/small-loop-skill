import { IconArchive, IconMinus, IconPin, IconX } from "@tabler/icons-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from "react";

import { type SlkApi, tauriApi } from "./api";
import { AppState, type AppStateValue } from "./components/AppState";
import { RunStrip } from "./components/RunStrip";
import { archivedRunSummaries, buildRunStripView, visibleRunSummaries } from "./runPresentation";
import { useSlkData } from "./useSlkData";
import { MESSAGE_CATALOG } from "./messages/catalog";
import { projectSupportedAuthoritativeMessages } from "./messages/messageFeed";
import {
  acknowledgeDisplayedMessages,
  bootstrapReadMarker,
  hasUnreadMessages,
  mergeReadMarker,
  parseReadMarker,
  type ReadMarker,
} from "./messages/readMarkers";
import { BI_VERSION } from "./version";
import { useWebBiSync } from "./webbi/useWebBiSync";
import "./styles/tokens.css";
import "./styles/app.css";

interface AppProps {
  api?: SlkApi;
}

function isTauri() {
  return "__TAURI_INTERNALS__" in window;
}

async function currentWindow() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow();
}

const MIN_WINDOW_HEIGHT = 94;

function fitRunSurface(shell: HTMLDivElement, availableHeight: number) {
  const surface = shell.querySelector<HTMLElement>(".runs-surface");
  const content = shell.querySelector<HTMLElement>(".runs-content");
  const rectHeight = (element: Element | null) => element?.getBoundingClientRect().height ?? 0;
  const borders = (element: Element) => {
    const style = window.getComputedStyle(element);
    return (Number.parseFloat(style.borderTopWidth) || 0) + (Number.parseFloat(style.borderBottomWidth) || 0);
  };
  const chrome = rectHeight(shell.querySelector(".control-bar")) + borders(shell);
  if (surface && content) {
    const blocks = Array.from(content.querySelectorAll<HTMLElement>(".slk-block"));
    const headers = blocks.map((block) => rectHeight(block.querySelector(".slk-row")) + borders(block));
    const headerBudget = headers.slice(0, 5).reduce((sum, height) => sum + height, 0);
    const details = content.querySelector<HTMLElement>(".run-details");
    const cellList = details?.querySelector<HTMLOListElement>(".cell-list");
    // Archive headings/empty copy are not Run rows. Only the single detail body is extra.
    const other = rectHeight(content) - headers.reduce((sum, height) => sum + height, 0) - rectHeight(details);
    if (cellList) {
      const rows = Array.from(cellList.children);
      const sixRows = rows.slice(0, 6).reduce((sum, row) => sum + rectHeight(row), 0);
      const fixedDetail = rectHeight(details) - rectHeight(cellList);
      const remaining = availableHeight - chrome - other - headerBudget - fixedDetail;
      const cellBudget = Math.min(sixRows, Math.max(rectHeight(rows[0] ?? null), remaining));
      cellList.style.maxHeight = `${cellBudget}px`;
    }
    surface.style.height = `${Math.max(0, Math.min(availableHeight - chrome, other + headerBudget + rectHeight(details)))}px`;
  } else {
    const state = shell.querySelector<HTMLElement>(".app-state");
    if (state) {
      // Measure the original intrinsic state before applying only the current work-area constraint.
      state.style.maxHeight = "";
      state.style.minHeight = "";
      state.style.overflowY = "";
      const stateBudget = Math.max(0, availableHeight - chrome);
      if (rectHeight(state) > stateBudget) {
        state.style.maxHeight = `${stateBudget}px`;
        state.style.minHeight = "0px";
        state.style.overflowY = "auto";
      }
    }
  }
  // Unlike scrollHeight this includes both shell borders and has no viewport minimum.
  return Math.max(MIN_WINDOW_HEIGHT, shell.getBoundingClientRect().height);
}

export function App({ api = tauriApi }: AppProps) {
  const [archiveVisible, setArchiveVisible] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const shell = useRef<HTMLDivElement>(null);
  const requestSize = useRef<(() => void) | null>(null);
  const [resizeError, setResizeError] = useState<string>();
  const { snapshot, staleReason, loading, refresh } = useSlkData(api);
  useWebBiSync(api, snapshot);
  const [readMarkers, setReadMarkers] = useState<Record<string, ReadMarker>>({});

  const messagesByRun = useMemo(
    () => new Map(
      (snapshot?.runDetails ?? []).map((run) => [
        run.run_id,
        projectSupportedAuthoritativeMessages(run, MESSAGE_CATALOG),
      ]),
    ),
    [snapshot],
  );

  const { activeRows, archivedRows } = useMemo(() => {
    if (!snapshot) return { activeRows: [], archivedRows: [] };
    const projects = new Map(
      snapshot.projects.projects.map((project) => [project.project_id, project]),
    );
    const details = new Map(snapshot.runDetails.map((run) => [run.run_id, run]));
    const build = (summaries: typeof snapshot.runs.runs) => summaries.flatMap((summary) => {
      const project = projects.get(summary.project_id);
      const run = details.get(summary.run_id);
      return project && run ? [buildRunStripView(project, run, new Date())] : [];
    });
    return {
      activeRows: build(visibleRunSummaries(snapshot.runs.runs)),
      archivedRows: build(archivedRunSummaries(snapshot.runs.runs)),
    };
  }, [snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    setReadMarkers((current) => {
      const next = { ...current };
      for (const [runId, messages] of messagesByRun) {
        const ids = messages.map((message) => message.message_id);
        const key = `le-bi:1.1:read:${snapshot.metadata.device_id}:${runId}`;
        const stored = next[runId] ?? parseReadMarker(window.localStorage.getItem(key));
        next[runId] = stored ? mergeReadMarker(stored, ids) : bootstrapReadMarker(ids);
        window.localStorage.setItem(key, JSON.stringify(next[runId]));
      }
      return next;
    });
  }, [messagesByRun, snapshot]);

  function acknowledgeRun(runId: string) {
    if (!snapshot) return;
    const ids = (messagesByRun.get(runId) ?? []).map((message) => message.message_id);
    const key = `le-bi:1.1:read:${snapshot.metadata.device_id}:${runId}`;
    setReadMarkers((current) => {
      const acknowledged = acknowledgeDisplayedMessages(
        current[runId] ?? bootstrapReadMarker([]),
        ids,
      );
      window.localStorage.setItem(key, JSON.stringify(acknowledged));
      return { ...current, [runId]: acknowledged };
    });
  }

  function unread(runId: string) {
    const marker = readMarkers[runId];
    return marker
      ? hasUnreadMessages(
          marker,
          (messagesByRun.get(runId) ?? []).map((message) => message.message_id),
        )
      : false;
  }

  function toggleRun(runId: string) {
    if (expandedRunId === runId) setExpandedRunId(null);
    else {
      acknowledgeRun(runId);
      setExpandedRunId(runId);
    }
  }

  useLayoutEffect(() => {
    if (expandedRunId && !activeRows.some((view) => view.runId === expandedRunId) &&
      (!archiveVisible || !archivedRows.some((view) => view.runId === expandedRunId))) {
      setExpandedRunId(null);
    }
  }, [activeRows, archivedRows, archiveVisible, expandedRunId]);

  useLayoutEffect(() => { requestSize.current?.(); });

  useEffect(() => {
    const currentShell = shell.current;
    if (!currentShell) return;
    const element = currentShell;
    let disposed = false;
    let revision = 0;
    let dirty = false;
    let running = false;
    let observedContent: Element | null = null;
    const unlisten: (() => void)[] = [];
    const nativeApi = isTauri()
      ? Promise.all([import("@tauri-apps/api/window"), import("@tauri-apps/api/dpi")])
      : null;
    const report = (error: unknown) => {
      if (!disposed) setResizeError(`窗口尺寸未更新：${error instanceof Error ? error.message : String(error)}`);
    };

    async function update() {
      running = true;
      while (dirty && !disposed) {
        dirty = false;
        const measurement = revision;
        try {
          if (nativeApi) {
            const [{ getCurrentWindow, currentMonitor }, { PhysicalSize, PhysicalPosition }] = await nativeApi;
            const appWindow = getCurrentWindow();
            const [monitor, position, size, outerSize] = await Promise.all([
              currentMonitor(), appWindow.outerPosition(), appWindow.innerSize(), appWindow.outerSize(),
            ]);
            if (disposed || measurement !== revision) continue;
            if (!monitor || !(monitor.scaleFactor > 0)) throw new Error("当前显示器工作区不可读");
            const scale = monitor.scaleFactor;
            const area = monitor.workArea;
            const bottom = area.position.y + area.size.height;
            // Native setSize targets the client area; workArea and outerPosition bound the whole window.
            const verticalFrame = Math.max(0, outerSize.height - size.height);
            const minimum = Math.ceil(MIN_WINDOW_HEIGHT * scale) + verticalFrame;
            if (area.size.height < minimum) throw new Error("当前工作区小于窗口必要最小高度");
            let top = position.y;
            // Only repair the bottom-edge/minimum-height conflict; ordinary expansion never moves the window.
            if (bottom - top < minimum) {
              top = bottom - minimum;
              await appWindow.setPosition(new PhysicalPosition(position.x, top));
              if (disposed || measurement !== revision) continue;
            }
            const physicalAvailable = Math.min(area.size.height, bottom - Math.max(top, area.position.y)) - verticalFrame;
            const height = fitRunSurface(element, Math.floor(physicalAvailable / scale));
            const physicalHeight = Math.min(physicalAvailable, Math.ceil(height * scale));
            if (disposed || measurement !== revision) continue;
            if (size.height !== physicalHeight) {
              await appWindow.setSize(new PhysicalSize(size.width, physicalHeight));
            }
          } else {
            fitRunSurface(element, window.screen.availHeight || Infinity);
          }
          if (!disposed && measurement === revision) setResizeError(undefined);
        } catch (error) {
          if (measurement === revision) report(error);
        }
      }
      running = false;
    }

    function schedule() {
      if (disposed) return;
      const content = element.querySelector(".runs-content");
      if (content !== observedContent) {
        if (observedContent) observer?.unobserve(observedContent);
        if (content) observer?.observe(content);
        observedContent = content;
      }
      revision += 1;
      dirty = true;
      if (!running) void update();
    }
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(element);
    requestSize.current = schedule;
    window.addEventListener("resize", schedule);
    if (nativeApi) {
      void nativeApi.then(([{ getCurrentWindow }]) => {
        const appWindow = getCurrentWindow();
        for (const registration of [appWindow.onMoved(schedule), appWindow.onScaleChanged(schedule)]) {
          void registration.then((stop) => disposed ? stop() : unlisten.push(stop)).catch(report);
        }
      }).catch(report);
    }
    schedule();
    return () => {
      disposed = true;
      requestSize.current = null;
      observer?.disconnect();
      window.removeEventListener("resize", schedule);
      unlisten.forEach((stop) => stop());
    };
  }, []);

  let appState: AppStateValue | undefined;
  if (!snapshot) {
    if (loading) appState = { kind: "loading" };
    else if (staleReason?.includes("SLK_BI_SCHEMA_UNSUPPORTED")) {
      appState = { kind: "unsupported", detail: staleReason };
    } else if (staleReason?.match(/config|not configured|No such file/i)) {
      appState = { kind: "unconfigured" };
    } else appState = { kind: "error", detail: staleReason ?? "Unknown read error" };
  } else if (activeRows.length === 0 && archivedRows.length === 0) {
    appState = { kind: "empty" };
  }

  async function togglePinned() {
    const next = !pinned;
    setPinned(next);
    if (isTauri()) await (await currentWindow()).setAlwaysOnTop(next);
  }

  function dragWindow(event: PointerEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest("button") || !isTauri()) return;
    void currentWindow().then((appWindow) => appWindow.startDragging());
  }

  return (
    <div className="app-shell" ref={shell}>
      <header className="control-bar" onPointerDown={dragWindow}>
        <span className="product-name">LE BI</span>
        <code className="product-version">{BI_VERSION}</code>
        {snapshot ? (
          <code className="device-identity" title={snapshot.metadata.device_id}>
            {snapshot.metadata.device_name} · {snapshot.metadata.device_id}
          </code>
        ) : null}
        {staleReason ? <span className="stale-notice" title={staleReason}>STALE</span> : null}
        {resizeError ? <span className="stale-notice" title={resizeError}>SIZE</span> : null}
        <div className="window-controls">
          <button
            type="button"
            className={archiveVisible ? "is-pressed" : ""}
            aria-label="归档箱"
            aria-pressed={archiveVisible}
            title="归档箱"
            onClick={() => setArchiveVisible((value) => !value)}
          ><IconArchive size={13} aria-hidden="true" /></button>
          <button
            type="button"
            className={pinned ? "is-pressed" : ""}
            aria-label="置顶"
            aria-pressed={pinned}
            title="置顶"
            onClick={() => void togglePinned()}
          ><IconPin size={13} aria-hidden="true" /></button>
          <button
            type="button"
            aria-label="最小化"
            title="最小化"
            onClick={() => isTauri() && void currentWindow().then((appWindow) => appWindow.minimize())}
          ><IconMinus size={13} aria-hidden="true" /></button>
          <button
            type="button"
            className="close-button"
            aria-label="关闭"
            title="关闭"
            onClick={() => isTauri() && void currentWindow().then((appWindow) => appWindow.close())}
          ><IconX size={13} aria-hidden="true" /></button>
        </div>
      </header>

      {appState ? (
        <AppState state={appState} onRetry={() => void refresh()} />
      ) : (
        <main className="runs-surface" tabIndex={0} aria-label="SLK Runs">
          <div className="runs-content">
          {activeRows.length ? (
            <ol
              className="run-strips active-run-strips"
              data-run-count={activeRows.length}
              aria-label="进行中的 SLK Runs"
            >
              {activeRows.map((view) => (
                <RunStrip
                  key={view.runId}
                  view={view}
                  unread={unread(view.runId)}
                  open={expandedRunId === view.runId}
                  onToggle={() => toggleRun(view.runId)}
                />
              ))}
            </ol>
          ) : (
            <p className="quiet-empty">当前没有进行中的 SLK</p>
          )}

          {archiveVisible ? (
            <section className="archive-panel" aria-label="归档箱">
              <header><strong>归档箱</strong><span>{archivedRows.length} 条归档 SLK</span></header>
              {archivedRows.length ? (
                <ol className="run-strips archive-strips" aria-label="已归档的 SLK Runs">
                  {archivedRows.map((view) => (
                    <RunStrip
                      key={view.runId}
                      view={view}
                      archived
                      unread={unread(view.runId)}
                      open={expandedRunId === view.runId}
                      onToggle={() => toggleRun(view.runId)}
                    />
                  ))}
                </ol>
              ) : <p className="quiet-empty">还没有归档记录</p>}
            </section>
          ) : null}
          </div>
        </main>
      )}
    </div>
  );
}
