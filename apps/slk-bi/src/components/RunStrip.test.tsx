import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildRunStripView } from "../runPresentation";
import { runFixture, twoRunFixture } from "../test/fixtures";
import { RunStrip } from "./RunStrip";

describe("RunStrip", () => {
  it("shows source context and expands into roles and CELL facts only", async () => {
    const user = userEvent.setup();
    const run = {
      ...runFixture,
      summary: {
        ...runFixture.summary,
        source_kind: "clk" as const,
        source_project_name: "LCapi 多模型接入",
        run_description: "统一 fallback、限流恢复和模型选择",
      },
    };
    const view = buildRunStripView(twoRunFixture.projects.projects[0]!, run, new Date());
    render(<RunStrip view={view} />);

    expect(screen.getByText("CLK · LCapi 多模型接入")).toBeVisible();
    expect(screen.getByText("统一 fallback、限流恢复和模型选择")).toBeVisible();
    expect(screen.queryByText("SUPERVISOR")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /展开 Close flow/ }));
    expect(screen.getByText("SUPERVISOR")).toBeVisible();
    expect(screen.getByText("qwen3.8-max")).toBeVisible();
    expect(screen.getByText("CELL 01")).toBeVisible();
    expect(screen.getByText("Implement closure")).toBeVisible();
    expect(screen.queryByText(/GO[- ]?001/)).not.toBeInTheDocument();
  });
});
