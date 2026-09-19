import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppState, type AppStateValue } from "./AppState";

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
});
