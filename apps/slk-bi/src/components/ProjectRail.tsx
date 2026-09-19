import { IconSearch } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import type { ProjectSummary, RunSummary } from "../contracts";

interface ProjectRailProps {
  projects: ProjectSummary[];
  runs: RunSummary[];
  selectedRunId?: string;
  onSelectRun: (runId: string) => void;
}

export function ProjectRail({ projects, runs, selectedRunId, onSelectRun }: ProjectRailProps) {
  const [query, setQuery] = useState("");
  const filteredRuns = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return runs;
    return runs.filter((run) => {
      const project = projects.find((item) => item.project_id === run.project_id);
      return [run.run_id, run.goal, run.state, project?.name]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(normalized));
    });
  }, [projects, query, runs]);

  function moveSelection(direction: -1 | 1) {
    if (!filteredRuns.length) return;
    const index = filteredRuns.findIndex((run) => run.run_id === selectedRunId);
    const next = Math.max(0, Math.min(filteredRuns.length - 1, index + direction));
    onSelectRun(filteredRuns[next]!.run_id);
  }

  return (
    <nav className="project-rail" aria-label="Projects and Runs">
      <div className="brand-lockup">
        <span className="brand-mark">SLK</span>
        <span>
          <strong>Loop BI</strong>
          <small>Read-only state</small>
        </span>
      </div>
      <label className="search-field">
        <IconSearch size={15} aria-hidden="true" />
        <span className="sr-only">Search projects and Runs</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search Runs"
        />
      </label>
      <div
        className="run-list"
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            moveSelection(1);
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            moveSelection(-1);
          }
        }}
      >
        {projects.map((project) => {
          const projectRuns = filteredRuns.filter((run) => run.project_id === project.project_id);
          if (!projectRuns.length) return null;
          return (
            <section key={project.project_id} className="project-group">
              <header>
                <span>{project.name}</span>
                <span>{projectRuns.length}</span>
              </header>
              {projectRuns.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  className="run-row"
                  aria-current={run.run_id === selectedRunId ? "page" : undefined}
                  tabIndex={run.run_id === selectedRunId ? 0 : -1}
                  onClick={() => onSelectRun(run.run_id)}
                >
                  <span>{run.goal}</span>
                  <small>
                    {run.run_id} · {run.closure_state}
                  </small>
                </button>
              ))}
            </section>
          );
        })}
      </div>
    </nav>
  );
}
