import type { EventProjection, RunView } from "../contracts";

interface RunOverviewProps {
  run: RunView;
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function latestFact(events: EventProjection[]) {
  const latest = events.at(-1)?.event_type;
  if (latest === "WORK_STARTED" || latest === "WORK_PROGRESS") return "Started, not delivered";
  if (latest === "CANDIDATE_SUBMITTED") return "Candidate delivered";
  if (latest === "D1_PASSED") return "Awaiting D2";
  if (latest === "RUN_CLOSED") return "Closed";
  return latest ? latest.replaceAll("_", " ").toLowerCase() : "No authored work fact";
}

export function RunOverview({ run }: RunOverviewProps) {
  const token = run.token_history.at(-1);
  const responsible = run.roles.find(
    (role) => role.role_instance_id === token?.to_role_instance_id,
  );

  return (
    <main className="run-overview">
      <header className="run-header">
        <div>
          <p className="eyebrow">{run.summary.run_id}</p>
          <h1>{run.summary.goal}</h1>
        </div>
        <span className={`state-pill state-${run.summary.state}`}>{run.summary.state}</span>
      </header>

      <section className="responsibility-strip" aria-label="Current responsibility">
        <div>
          <span className="section-label">SLK TOKEN</span>
          <strong>
            Responsibility: {responsible ? titleCase(responsible.role) : "Unassigned"}
          </strong>
        </div>
        <div className="fact-boundary">
          <span>Latest recorded fact</span>
          <strong>{latestFact(run.events)}</strong>
        </div>
      </section>

      <section className="serial-section" aria-labelledby="serial-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Serial execution</p>
            <h2 id="serial-heading">GO and CELL path</h2>
          </div>
          <span>Plan revision {run.summary.current_plan_revision}</span>
        </div>
        <ol className="go-track">
          {[...run.go_nodes]
            .sort((left, right) => left.ordinal - right.ordinal)
            .map((go) => (
              <li key={go.go_id} className="go-node">
                <div className="go-title" data-testid="go-node">
                  <code>{go.go_id}</code>
                  <strong>{go.title}</strong>
                </div>
                <span className="node-state">{go.state}</span>
                <ol className="cell-track">
                  {[...go.cell_nodes]
                    .sort((left, right) => left.ordinal - right.ordinal)
                    .map((cell) => (
                      <li key={cell.cell_id}>
                        <span>
                          <code>{cell.cell_id}</code>
                          {cell.title}
                        </span>
                        <small>
                          attempt {cell.attempt} · {cell.state}
                        </small>
                      </li>
                    ))}
                </ol>
              </li>
            ))}
        </ol>
      </section>
    </main>
  );
}
