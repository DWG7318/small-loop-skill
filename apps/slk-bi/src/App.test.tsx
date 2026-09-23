import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { SlkApi } from "./api";
import { App } from "./App";
import { fixtureApi, runFixture, twoRunFixture } from "./test/fixtures";

function activeRunApi(count: number): SlkApi {
  const summaries = Array.from({ length: count }, (_, index) => ({
    ...runFixture.summary,
    run_id: `run-${index + 1}`,
    run_name: `Active run ${index + 1}`,
    lineage_root_run_id: `run-${index + 1}`,
  }));
  const details = summaries.map((summary) => ({
    ...runFixture,
    run_id: summary.run_id,
    summary,
  }));
  return {
    ...fixtureApi,
    projects: async () => ({
      ...twoRunFixture.projects,
      projects: [{ ...twoRunFixture.projects.projects[0]!, run_count: count }],
    }),
    runs: async () => ({ ...twoRunFixture.runs, runs: summaries }),
    run: async (runId) => details.find((run) => run.run_id === runId)!,
  };
}

afterEach(cleanup);

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

  it.each([
    [5, false],
    [6, true],
  ])("marks vertical scrolling only after five active Runs", async (count, scrollable) => {
    render(<App api={activeRunApi(count)} />);

    const list = await screen.findByRole("list", { name: "进行中的 SLK Runs" });
    expect(list).toHaveAttribute("data-run-count", String(count));
    expect(list).toHaveClass("active-run-strips");
    if (scrollable) expect(list).toHaveClass("is-scrollable");
    else expect(list).not.toHaveClass("is-scrollable");
  });
});
