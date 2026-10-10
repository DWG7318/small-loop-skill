import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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

beforeEach(() => window.localStorage.clear());
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

  it.each([5, 6, 10])("keeps all %i Runs in one keyboard-reachable outer scroll surface", async (count) => {
    render(<App api={activeRunApi(count)} />);

    const list = await screen.findByRole("list", { name: "进行中的 SLK Runs" });
    expect(list).toHaveAttribute("data-run-count", String(count));
    expect(list).toHaveClass("active-run-strips");
    expect(list).not.toHaveClass("is-scrollable");
    const main = screen.getByRole("main", { name: "SLK Runs" });
    expect(main).toHaveAttribute("tabindex", "0");
    expect(main).toContainElement(list);
    expect(list.children).toHaveLength(count);
  });

  it("allows only one expanded Run across active and archive, and toggles it closed", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} />);
    await user.click(await screen.findByRole("button", { name: "展开 Close flow" }));
    await user.click(screen.getByRole("button", { name: "归档箱" }));
    await user.click(screen.getByRole("button", { name: "展开 Previous attempt" }));
    expect(screen.getByRole("button", { name: "展开 Close flow" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "收起 Previous attempt" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("list", { name: /CELL 记录/ })).toHaveLength(1);
    expect(screen.getByRole("main")).toContainElement(screen.getByRole("list", { name: "已归档的 SLK Runs" }));
    await user.click(screen.getByRole("button", { name: "收起 Previous attempt" }));
    expect(screen.queryByRole("list", { name: /CELL 记录/ })).not.toBeInTheDocument();
  });

  it("shows BI 1.1.0 and the exact local device identity in the header", async () => {
    render(<App api={fixtureApi} />);

    expect(await screen.findByText("1.1.0")).toBeVisible();
    expect(screen.getByText("Workstation A · device-a")).toBeVisible();
  });

  it("clears archived disclosure when its archive surface closes", async () => {
    const user = userEvent.setup();
    render(<App api={fixtureApi} />);
    await screen.findByText("Close flow");
    await user.click(screen.getByRole("button", { name: "归档箱" }));
    await user.click(screen.getByRole("button", { name: "展开 Previous attempt" }));
    await user.click(screen.getByRole("button", { name: "归档箱" }));
    expect(screen.queryByRole("list", { name: /CELL 记录/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "归档箱" }));
    expect(screen.getByRole("button", { name: "展开 Previous attempt" })).toHaveAttribute("aria-expanded", "false");
  });

  it.each(["archived", "removed"])("clears disclosure after a poll makes its Run %s and invisible", async (change) => {
    const user = userEvent.setup();
    let summaries = [runFixture.summary];
    const api: SlkApi = {
      ...fixtureApi,
      runs: async () => ({ ...twoRunFixture.runs, runs: summaries }),
      run: async () => ({ ...runFixture, summary: summaries[0] ?? runFixture.summary }),
    };
    render(<App api={api} />);
    await user.click(await screen.findByRole("button", { name: "展开 Close flow" }));
    summaries = change === "archived" ? [{ ...runFixture.summary, closure_state: "closed", state: "archived" }] : [];
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "收起 Close flow" })).not.toBeInTheDocument());
    expect(screen.queryByRole("list", { name: /CELL 记录/ })).not.toBeInTheDocument();
    if (change === "archived") {
      await user.click(screen.getByRole("button", { name: "归档箱" }));
      expect(screen.getByRole("button", { name: "展开 Close flow" })).toHaveAttribute("aria-expanded", "false");
    } else {
      summaries = [runFixture.summary];
      window.dispatchEvent(new Event("focus"));
      expect(await screen.findByRole("button", { name: "展开 Close flow" })).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("renders a blocked CELL as a visible business state instead of an empty shell", async () => {
    const api: SlkApi = {
      ...fixtureApi,
      run: async () => ({
        ...runFixture,
        events: [
          ...runFixture.events,
          {
            ...runFixture.events[0]!,
            event_id: "blocked-current-cell",
            event_type: "BLOCKER_REPORTED",
            occurred_at: "2026-09-20T00:00:05Z",
          },
        ],
      }),
    };
    const { container } = render(<App api={api} />);

    expect(await screen.findByText("需要处理")).toBeVisible();
    expect(container.querySelector(".app-shell")).toBeInTheDocument();
  });

  it("keeps the shell visible and can retry an initial backend failure", async () => {
    const user = userEvent.setup();
    let unavailable = true;
    const api: SlkApi = {
      ...fixtureApi,
      metadata: async () => {
        if (unavailable) throw new Error("backend offline");
        return fixtureApi.metadata();
      },
    };
    render(<App api={api} />);

    expect(await screen.findByText("State could not be read")).toBeVisible();
    expect(screen.getByText("LE BI")).toBeVisible();
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "Retry read" }));
    expect(await screen.findByText("Project A")).toBeVisible();
  });

  it("shows a registered Overwatcher as a complete fourth role", async () => {
    const api: SlkApi = {
      ...fixtureApi,
      run: async () => ({
        ...runFixture,
        roles: [
          ...runFixture.roles,
          {
            ...runFixture.roles[0]!,
            role: "overwatcher",
            role_instance_id: "overwatcher-a",
            agent_runtime: "LCaS",
            model: "gpt-6-luna",
            reasoning: "high",
            session_id: "overwatcher-session-a",
          },
        ],
      }),
    };
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(await screen.findByRole("button", { name: "展开 Close flow" }));
    expect(screen.getByText("OVERWATCHER")).toBeVisible();
    expect(screen.getByText("LCaS")).toBeVisible();
    expect(screen.getByText(/gpt-6-luna/)).toBeVisible();
  });

  it("creates a compact green dot only after a new authoritative message and clears it on open", async () => {
    const user = userEvent.setup();
    let current = runFixture;
    const api: SlkApi = {
      ...fixtureApi,
      run: async () => current,
    };
    render(<App api={api} />);

    await screen.findByText("Close flow");
    expect(screen.queryByLabelText("有新消息")).not.toBeInTheDocument();

    current = {
      ...runFixture,
      events: [
        ...runFixture.events,
        {
          ...runFixture.events[0]!,
          event_id: "work-progress",
          event_type: "WORK_PROGRESS",
          occurred_at: "2026-09-20T00:00:04Z",
        },
      ],
    };
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByLabelText("有新消息")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "展开 Close flow" }));
    expect(screen.queryByLabelText("有新消息")).not.toBeInTheDocument();

    current = { ...current, events: [...current.events, {
      ...runFixture.events[0]!, event_id: "progress-while-open", event_type: "WORK_PROGRESS",
      occurred_at: "2026-09-20T00:00:05Z",
    }] };
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByLabelText("有新消息")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "收起 Close flow" }));
    expect(screen.getByLabelText("有新消息")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "展开 Close flow" }));
    expect(screen.queryByLabelText("有新消息")).not.toBeInTheDocument();
  });
});
