import { Component, type ReactNode } from "react";

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

function reloadBi() {
  window.location.reload();
}

export function InterfaceFailure({ detail }: { detail: string }) {
  return (
    <div className="app-shell">
      <main className="app-state state-error" role="alert">
        <div className="app-state-mark" aria-hidden="true" />
        <p className="eyebrow">Visible failure boundary</p>
        <h1>BI interface could not be rendered</h1>
        <p>The read-only window stayed visible. Reload the interface or report this code.</p>
        <code>{detail}</code>
        <button className="state-reload" type="button" onClick={reloadBi}>Reload BI</button>
      </main>
    </div>
  );
}

interface UiFailureBoundaryState {
  failed: boolean;
}

export class UiFailureBoundary extends Component<{ children: ReactNode }, UiFailureBoundaryState> {
  state: UiFailureBoundaryState = { failed: false };

  static getDerivedStateFromError(): UiFailureBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("SLK_BI_RENDER_FAILED", error);
  }

  render() {
    return this.state.failed
      ? <InterfaceFailure detail="SLK_BI_RENDER_FAILED" />
      : this.props.children;
  }
}
