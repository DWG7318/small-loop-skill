import { IconArchive, IconMinus, IconPin, IconX } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";

import { type SlkApi, tauriApi } from "./api";
import { AppState, type AppStateValue } from "./components/AppState";
import { RunStrip } from "./components/RunStrip";
import { archivedRunSummaries, buildRunStripView, visibleRunSummaries } from "./runPresentation";
import { useSlkData } from "./useSlkData";

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

export function App({ api = tauriApi }: AppProps) {
  const [archiveVisible, setArchiveVisible] = useState(false);
  const [pinned, setPinned] = useState(false);
  const shell = useRef<HTMLDivElement>(null);
  const { snapshot, staleReason, loading } = useSlkData(api);

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
    if (!isTauri() || !shell.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const height = Math.min(720, Math.max(94, shell.current?.scrollHeight ?? 94));
      void Promise.all([currentWindow(), import("@tauri-apps/api/dpi")]).then(
        ([appWindow, { LogicalSize }]) => appWindow.setSize(new LogicalSize(940, height)),
      );
    });
    observer.observe(shell.current);
    return () => observer.disconnect();
  }, [activeRows.length, archivedRows.length, archiveVisible]);

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
        <code className="product-version">1.0</code>
        {staleReason ? <span className="stale-notice" title={staleReason}>STALE</span> : null}
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
        <AppState state={appState} />
      ) : (
        <main className="runs-surface" aria-label="SLK Runs">
          {activeRows.length ? (
            <ol className="run-strips" aria-label="进行中的 SLK Runs">
              {activeRows.map((view) => <RunStrip key={view.runId} view={view} />)}
            </ol>
          ) : (
            <p className="quiet-empty">当前没有进行中的 SLK</p>
          )}

          {archiveVisible ? (
            <section className="archive-panel" aria-label="归档箱">
              <header><strong>归档箱</strong><span>{archivedRows.length} 条归档 SLK</span></header>
              {archivedRows.length ? (
                <ol className="run-strips archive-strips" aria-label="已归档的 SLK Runs">
                  {archivedRows.map((view) => <RunStrip key={view.runId} view={view} archived />)}
                </ol>
              ) : <p className="quiet-empty">还没有归档记录</p>}
            </section>
          ) : null}
        </main>
      )}
    </div>
  );
}
