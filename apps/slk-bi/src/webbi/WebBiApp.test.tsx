import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MESSAGE_CATALOG } from "../messages/catalog";
import { runFixture } from "../test/fixtures";
import type { AuthoritativeMessage } from "../messages/messageFeed";
import { WebBiApp } from "./WebBiApp";
import type { PublicNotificationSettings } from "./notifications";
import type { WebBiArchiveRecord } from "./worker";
import type { WebBiApi } from "./webApi";

const message: AuthoritativeMessage = {
  message_id: "EVENT:work-started",
  run_id: "run-a",
  source_kind: "EVENT",
  source_id: "work-started",
  message_type: "WORK_STARTED",
  label_zh: "Worker 开始工作",
  author_role: "worker",
  author_identity_ref: "worker-a",
  go_id: "GO-001",
  cell_id: "CELL-001",
  attempt: 1,
  occurred_at: "2026-10-04T00:00:00Z",
};

function record(archived = false): WebBiArchiveRecord {
  const roles = [
    ...runFixture.roles,
    {
      ...runFixture.roles[0]!,
      role: "overwatcher" as const,
      role_instance_id: "overwatcher-a",
      agent_runtime: "LCaS",
      model: "gpt-6-luna",
      reasoning: "high",
      session_id: "overwatcher-session-a",
    },
  ];
  return {
    device: { device_id: "device-a", device_name: "Workstation A" },
    run: archived
      ? {
          ...runFixture,
          roles,
          summary: {
            ...runFixture.summary,
            state: "archived",
            closure_state: "closed",
            archived_at: "2026-10-04T00:05:00Z",
          },
        }
      : { ...runFixture, roles },
    messages: [message],
    updated_at: "2026-10-04T00:01:00Z",
  };
}

const settings: PublicNotificationSettings = {
  enabled: true,
  server_url: "https://ntfy.example.test",
  topic: "slk",
  auth_mode: "password",
  username: "DWG",
  has_secret: true,
  selection_mode: "selected",
  selected_message_types: ["EVENT:WORK_STARTED"],
  config_version: 2,
};

function api(): WebBiApi {
  return {
    listRuns: vi.fn(async (archived) => archived ? [record(true)] : [record(false)]),
    getRun: vi.fn(async (_deviceId, _runId) => record(false)),
    catalog: vi.fn(async () => MESSAGE_CATALOG),
    getNotificationSettings: vi.fn(async () => settings),
    saveNotificationSettings: vi.fn(async () => settings),
    testNotification: vi.fn(async () => undefined),
  };
}

beforeEach(() => {
  window.location.hash = "#/";
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("WebBI 1.1 browser UI", () => {
  it("starts with 进行中, has no 全部 filter, and opens an isolated Run detail", async () => {
    render(<WebBiApp api={api()} />);
    expect(await screen.findByRole("heading", { name: "Run 一览" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "全部" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进行中" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText((_, element) => element?.textContent === "电脑 Workstation A · device-a")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: /Close flow/ }));
    expect(await screen.findByRole("heading", { name: "Close flow" })).toBeInTheDocument();
    expect(screen.getByText("Workstation A · device-a")).toBeInTheDocument();
    expect(screen.getByText("Supervisor")).toBeInTheDocument();
    expect(screen.getByText("Checker")).toBeInTheDocument();
    expect(screen.getByText("Worker")).toBeInTheDocument();
    expect(screen.getByText("Overwatcher")).toBeInTheDocument();
    expect(screen.getByText("LCaS")).toBeInTheDocument();
  });

  it("switches to the permanent archive without mixing it into the active list", async () => {
    const mock = api();
    render(<WebBiApp api={mock} />);
    await screen.findByText("Close flow");
    fireEvent.click(screen.getByRole("button", { name: "已归档" }));
    await waitFor(() => expect(mock.listRuns).toHaveBeenLastCalledWith(true));
    expect(screen.getByText("已归档的 Run 永久保留，只读查看。")) .toBeInTheDocument();
  });

  it("creates an unread badge only after a later authoritative message and clears it on open", async () => {
    vi.useFakeTimers();
    const mock = api();
    let calls = 0;
    vi.mocked(mock.listRuns).mockImplementation(async () => {
      calls += 1;
      const base = record(false);
      return calls === 1 ? [base] : [{
        ...base,
        messages: [
          ...base.messages,
          { ...message, message_id: "EVENT:work-progress", source_id: "work-progress", message_type: "WORK_PROGRESS", label_zh: "Worker 记录进展" },
        ],
      }];
    });
    render(<WebBiApp api={mock} />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("Close flow")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(screen.getByText("有更新")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Close flow/ }));
    expect(screen.queryByText("有更新")).not.toBeInTheDocument();
  });

  it("edits ntfy using only exact catalog types and never renders the stored secret", async () => {
    render(<WebBiApp api={api()} />);
    fireEvent.click(await screen.findByRole("link", { name: "手机通知" }));
    expect(await screen.findByRole("heading", { name: "手机通知" })).toBeInTheDocument();
    expect(screen.getByLabelText("服务器地址")).toHaveValue("https://ntfy.example.test");
    expect(screen.getByLabelText("用户名")).toHaveValue("DWG");
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Topic 名称")).toHaveValue("slk");
    expect(screen.getByText("已保存凭据；留空即保留")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("private-token")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Worker 开始工作/ })).toBeChecked();
    expect(screen.queryByText("进度变化")).not.toBeInTheDocument();
  });
});
