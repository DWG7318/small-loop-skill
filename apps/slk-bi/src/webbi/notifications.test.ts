import { describe, expect, it } from "vitest";

import type { AuthoritativeMessage } from "../messages/messageFeed";
import {
  notificationKey,
  selectMessagesForNotification,
  toPublicNotificationSettings,
} from "./notifications";

const messages: AuthoritativeMessage[] = [
  {
    message_id: "EVENT:a",
    run_id: "run-a",
    source_kind: "EVENT",
    source_id: "a",
    message_type: "WORK_STARTED",
    label_zh: "Worker 开始工作",
    author_role: "worker",
    author_identity_ref: "worker-a",
    go_id: "GO-001",
    cell_id: "CELL-001",
    attempt: 1,
    occurred_at: "2026-10-04T00:00:00Z",
  },
  {
    message_id: "EVENT:b",
    run_id: "run-a",
    source_kind: "EVENT",
    source_id: "b",
    message_type: "D1_PASSED",
    label_zh: "D1 已通过",
    author_role: "checker",
    author_identity_ref: "checker-a",
    go_id: "GO-001",
    cell_id: "CELL-001",
    attempt: 1,
    occurred_at: "2026-10-04T00:01:00Z",
  },
];

describe("WebBI ntfy selection", () => {
  it("selects exact catalog keys and keeps delivery ids idempotent", () => {
    const selected = selectMessagesForNotification(messages, {
      selection_mode: "selected",
      selected_message_types: ["EVENT:D1_PASSED"],
    });
    expect(selected.map((item) => item.message_id)).toEqual(["EVENT:b"]);
    expect(notificationKey(3, "device-a", selected[0]!)).toBe(
      "3:device-a:EVENT:b",
    );
  });

  it("never returns the stored ntfy secret to the browser", () => {
    expect(
      toPublicNotificationSettings({
        enabled: true,
        server_url: "https://ntfy.example.test",
        topic: "slk",
        auth_mode: "token",
        username: null,
        encrypted_secret: "ciphertext",
        secret_iv: "iv",
        selection_mode: "all",
        selected_message_types: [],
        config_version: 2,
      }),
    ).toEqual({
      enabled: true,
      server_url: "https://ntfy.example.test",
      topic: "slk",
      auth_mode: "token",
      username: null,
      has_secret: true,
      selection_mode: "all",
      selected_message_types: [],
      config_version: 2,
    });
  });
});
