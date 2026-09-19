export type AppStateValue =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "empty" }
  | { kind: "unsupported"; detail?: string }
  | { kind: "error"; detail: string };

const copy: Record<AppStateValue["kind"], { title: string; body: string }> = {
  loading: {
    title: "Reading SLK state",
    body: "Opening the configured machine-wide state authority in read-only mode.",
  },
  unconfigured: {
    title: "SLK state is not configured",
    body: "Complete SLK state-core configuration outside this read-only BI, then refresh.",
  },
  empty: {
    title: "No SLK Runs yet",
    body: "The configured state root is healthy and contains no registered Runs.",
  },
  unsupported: {
    title: "Unsupported state schema",
    body: "This BI stopped interpreting fields because the stored projection is newer than it supports.",
  },
  error: {
    title: "State could not be read",
    body: "The read failed without changing the configured state root.",
  },
};

export function AppState({ state }: { state: AppStateValue }) {
  const message = copy[state.kind];
  return (
    <main className={`app-state state-${state.kind}`} aria-live="polite">
      <div className="app-state-mark" aria-hidden="true" />
      <p className="eyebrow">Read-only boundary</p>
      <h1>{message.title}</h1>
      <p>{message.body}</p>
      {"detail" in state && state.detail ? <code>{state.detail}</code> : null}
      {state.kind === "loading" ? (
        <div className="state-skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ) : null}
    </main>
  );
}
