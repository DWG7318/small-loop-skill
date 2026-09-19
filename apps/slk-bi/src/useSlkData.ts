import { useCallback, useEffect, useRef, useState } from "react";

import type { SlkApi } from "./api";
import type { ProjectsView, RunsView, RunView } from "./contracts";

export interface SlkSnapshot {
  projects: ProjectsView;
  runs: RunsView;
  run?: RunView;
}

export function useSlkData(api: SlkApi, selectedRunId?: string) {
  const [snapshot, setSnapshot] = useState<SlkSnapshot>();
  const [staleReason, setStaleReason] = useState<string>();
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>();
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [projects, runs, run] = await Promise.all([
        api.projects(),
        api.runs(),
        selectedRunId ? api.run(selectedRunId) : Promise.resolve(undefined),
      ]);
      if (!mounted.current) return;
      setSnapshot({ projects, runs, ...(run ? { run } : {}) });
      setStaleReason(undefined);
      setLastUpdatedAt(new Date().toISOString());
    } catch (error) {
      if (mounted.current) {
        setStaleReason(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [api, selectedRunId]);

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
