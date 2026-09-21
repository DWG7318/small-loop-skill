import { useCallback, useEffect, useRef, useState } from "react";

import type { SlkApi } from "./api";
import type { ProjectsView, RunsView, RunView } from "./contracts";

export interface SlkSnapshot {
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

  const refresh = useCallback(async () => {
    try {
      const [projects, runs] = await Promise.all([
        api.projects(),
        api.runs(),
      ]);
      const runDetails = await Promise.all(
        runs.runs.map((run) => api.run(run.run_id)),
      );
      if (!mounted.current) return;
      setSnapshot({ projects, runs, runDetails });
      setStaleReason(undefined);
      setLastUpdatedAt(new Date().toISOString());
    } catch (error) {
      if (mounted.current) {
        setStaleReason(error instanceof Error ? error.message : String(error));
      }
    } finally {
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
