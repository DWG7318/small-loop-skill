import { IconLayoutSidebarRight, IconRefresh } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { type SlkApi, tauriApi } from "./api";
import { ProjectRail } from "./components/ProjectRail";
import { RunOverview } from "./components/RunOverview";
import { useSlkData } from "./useSlkData";

interface AppProps {
  api?: SlkApi;
}

export function App({ api = tauriApi }: AppProps) {
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const { snapshot, staleReason, lastUpdatedAt, loading, refresh } = useSlkData(api, selectedRunId);

  useEffect(() => {
    if (!selectedRunId && snapshot?.runs.runs[0]) {
      setSelectedRunId(snapshot.runs.runs[0].run_id);
    }
  }, [selectedRunId, snapshot]);

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
            <RunOverview run={snapshot.run} />
          ) : (
            <main className="run-overview empty-workspace" aria-live="polite">
              {loading ? "Loading SLK state…" : "Select a Run"}
            </main>
          )}
          {inspectorOpen ? (
            <aside className="inspector-placeholder" aria-label="Inspector">
              <p className="eyebrow">Inspector</p>
              <h2>Recorded facts</h2>
              <p>Select a role, event, correction, or evidence record to inspect its provenance.</p>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
