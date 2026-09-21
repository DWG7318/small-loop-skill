import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { fixtureApi } from "./test/fixtures";

describe("LE BI shell", () => {
  it("shows active SLKs and keeps archived SLKs in a separate expandable view", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} />);

    expect(await screen.findByText("LE BI")).toBeVisible();
    expect(screen.getByText("Project A")).toBeVisible();
    expect(screen.getByText("Close flow")).toBeVisible();
    expect(screen.getByText(/0\/1 CELL/)).toBeVisible();
    expect(screen.getByText(/SLK 4\.1\.0/)).toBeVisible();
    expect(screen.queryByText("Previous attempt")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "归档箱" }));
    expect(await screen.findByText("Previous attempt")).toBeVisible();
    expect(screen.getByText("1 条归档 SLK")).toBeVisible();

    expect(screen.queryByRole("navigation", { name: "Projects and Runs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.queryByText("Timeline")).not.toBeInTheDocument();
    expect(screen.queryByText(/GO\s*and\s*CELL/i)).not.toBeInTheDocument();
  });
});
