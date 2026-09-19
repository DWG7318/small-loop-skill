import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { fixtureApi } from "./test/fixtures";

describe("SLK BI shell", () => {
  it("shows multiple Runs and the selected Run's exact responsibility boundary", async () => {
    render(<App api={fixtureApi} />);

    expect(await screen.findByText("Acceptance A")).toBeVisible();
    expect(screen.getByText("Acceptance B")).toBeVisible();
    expect(await screen.findByText("Responsibility: Worker")).toBeVisible();
    expect(screen.getByText("Started, not delivered")).toBeVisible();
    expect(screen.getAllByTestId("go-node").map((node) => node.textContent)).toEqual([
      "GO-001Close flow",
    ]);
  });
});
