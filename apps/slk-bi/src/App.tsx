import { IconLayoutSidebarRight, IconRefresh } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { type SlkApi, tauriApi } from "./api";
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
          {snapshot?.run ? (
            <RunOverview
              run={snapshot.run}
              onSelectEvent={(event) => {
                setSelection({ kind: "event", value: event });
                setInspectorOpen(true);
              }}
            />
          ) : (
            <main className="run-overview empty-workspace" aria-live="polite">
              {loading ? "Loading SLK state…" : "Select a Run"}
            </main>
          )}
          {inspectorOpen ? <Inspector selection={selection} /> : null}
        </div>
      </div>
    </div>
  );
}
