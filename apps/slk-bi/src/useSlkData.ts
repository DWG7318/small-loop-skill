import { useCallback, useEffect, useRef, useState } from "react";

import type { BiMetadata, SlkApi } from "./api";
import type { ProjectsView, RunsView, RunView } from "./contracts";

export interface SlkSnapshot {
  metadata: BiMetadata;
  projects: ProjectsView;
  runs: RunsView;
  runDetails: RunView[];
}

export function useSlkData(api: SlkApi) {
  const [snapshot, setSnapshot] = useState<SlkSnapshot>();
  const [staleReason, setStaleReason] = useState<string>();
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>();
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);
  const refreshing = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const [metadata, projects, runs] = await Promise.all([
        api.metadata(),
        api.projects(),
        api.runs(),
      ]);
      const results = await Promise.allSettled(
        runs.runs.map((run) => api.run(run.run_id)),
      );
      const runDetails = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
      const warnings = [...(projects.source_warnings ?? []), ...(runs.source_warnings ?? []),
        ...results.flatMap((result, index) => result.status === "rejected" ? [`${runs.runs[index]!.run_id}: ${String(result.reason)}`] : [])];
      if (!mounted.current) return;
      setSnapshot({ metadata, projects, runs, runDetails });
      setStaleReason(warnings.length ? [...new Set(warnings)].join("; ") : undefined);
      setLastUpdatedAt(new Date().toISOString());
    } catch (error) {
      if (mounted.current) {
        setStaleReason(error instanceof Error ? error.message : String(error));
      }
    } finally {
      refreshing.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 3_000);
    return () => {
      mounted.current = false;
      window.removeEventListener("focus", onFocus);
      window.clearInterval(timer);
    };
  }, [refresh]);

  return { snapshot, staleReason, lastUpdatedAt, loading, refresh };
}
