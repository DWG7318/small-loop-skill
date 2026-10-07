import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppState, UiFailureBoundary, type AppStateValue } from "./AppState";

function BrokenView(): never {
  throw new Error("render failed");
}

describe("AppState", () => {
  it.each<[AppStateValue, string]>([
    [{ kind: "unconfigured" }, "SLK state is not configured"],
    [{ kind: "empty" }, "No SLK Runs yet"],
    [{ kind: "unsupported", detail: "slk.bi.run/v2" }, "Unsupported state schema"],
  ])("renders $state.kind without a write action", (state, text) => {
    render(<AppState state={state} />);
    expect(screen.getByText(text)).toBeVisible();
    expect(screen.queryByRole("button", { name: /configure|repair|approve/i })).not.toBeInTheDocument();
  });

  it("keeps a visible recovery surface when a child render fails", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<UiFailureBoundary><BrokenView /></UiFailureBoundary>);

    expect(screen.getByText("BI interface could not be rendered")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reload BI" })).toBeVisible();
    consoleError.mockRestore();
  });
});
