import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { fixtureApi } from "./test/fixtures";

describe("SLK BI accessibility boundaries", () => {
  it("has named navigation, main, inspector, and utility controls", async () => {
    render(<App api={fixtureApi} />);
    expect(await screen.findByText("Responsibility: Worker")).toBeVisible();
    expect(await screen.findByRole("navigation", { name: "Projects and Runs" })).toBeVisible();
    expect(await screen.findByRole("main")).toBeVisible();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh state" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeVisible();
  });
});
