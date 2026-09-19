import { IconLayoutSidebarRight, IconMoon, IconRefresh, IconSun } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { type SlkApi, tauriApi } from "./api";
import { AppState, type AppStateValue } from "./components/AppState";
import { Inspector, type InspectorSelection } from "./components/Inspector";
import { ProjectRail } from "./components/ProjectRail";
import { RunOverview } from "./components/RunOverview";
import { useSlkData } from "./useSlkData";

interface AppProps {
  api?: SlkApi;
}

export function App({ api = tauriApi }: AppProps) {
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [selection, setSelection] = useState<InspectorSelection>();
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = window.localStorage.getItem("slk-bi-theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });
  const { snapshot, staleReason, lastUpdatedAt, loading, refresh } = useSlkData(api, selectedRunId);

  useEffect(() => {
    if (!selectedRunId && snapshot?.runs.runs[0]) {
      setSelectedRunId(snapshot.runs.runs[0].run_id);
    }
  }, [selectedRunId, snapshot]);

  useEffect(() => {
    const activeRole = snapshot?.run?.roles.find((role) => role.lifecycle === "active");
    if (activeRole) setSelection({ kind: "role", value: activeRole });
  }, [snapshot?.run?.run_id]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("slk-bi-theme", theme);
  }, [theme]);

  let appState: AppStateValue | undefined;
  if (!snapshot) {
    if (loading) appState = { kind: "loading" };
    else if (staleReason?.includes("SLK_BI_SCHEMA_UNSUPPORTED")) {
      appState = { kind: "unsupported", detail: staleReason };
    } else if (staleReason?.match(/config|not configured|No such file/i)) {
      appState = { kind: "unconfigured" };
    } else appState = { kind: "error", detail: staleReason ?? "Unknown read error" };
  } else if (snapshot.runs.runs.length === 0) {
    appState = { kind: "empty" };
  }

  return (
    <div className="app-shell">
      <ProjectRail
        projects={snapshot?.projects.projects ?? []}
        runs={snapshot?.runs.runs ?? []}
        selectedRunId={selectedRunId}
        onSelectRun={setSelectedRunId}
      />
      <div className="workspace">
        <header className="utility-bar">
          <div>
            {staleReason ? (
              <span className="stale-notice">Stale · {staleReason}</span>
            ) : (
              <span>{lastUpdatedAt ? `Updated ${lastUpdatedAt}` : "Reading global state"}</span>
            )}
          </div>
          <div className="utility-actions">
            <button
              type="button"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
              aria-label="Toggle theme"
              aria-pressed={theme === "light"}
            >
              {theme === "dark" ? (
                <IconSun size={16} aria-hidden="true" />
              ) : (
                <IconMoon size={16} aria-hidden="true" />
              )}
            </button>
            <button type="button" onClick={() => void refresh()} aria-label="Refresh state">
              <IconRefresh size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setInspectorOpen((open) => !open)}
              aria-label="Toggle inspector"
              aria-pressed={inspectorOpen}
            >
              <IconLayoutSidebarRight size={16} aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className={`content-grid${inspectorOpen ? " inspector-visible" : ""}`}>
          {appState ? (
            <AppState state={appState} />
          ) : snapshot?.run ? (
            <RunOverview
              run={snapshot.run}
              onSelectEvent={(event) => {
                setSelection({ kind: "event", value: event });
                setInspectorOpen(true);
              }}
            />
          ) : (
            <main className="run-overview empty-workspace" aria-live="polite">
              Select a Run
            </main>
          )}
          {inspectorOpen ? <Inspector selection={selection} /> : null}
        </div>
      </div>
    </div>
  );
}
