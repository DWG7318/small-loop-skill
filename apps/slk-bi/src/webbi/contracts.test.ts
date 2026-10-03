import { describe, expect, it } from "vitest";

import type { RunView } from "../contracts";
import { runFixture } from "../test/fixtures";
import type { AuthoritativeMessage, MessageCatalogEntry } from "../messages/messageFeed";
import {
  parseNotificationSettingsInput,
  parseUploadEnvelope,
  type WebBiUploadEnvelope,
} from "./contracts";

const catalog: MessageCatalogEntry[] = [
  {
    source_kind: "EVENT",
    message_type: "WORK_STARTED",
    label_zh: "Worker 开始工作",
    allowed_roles: ["worker"],
    notification_eligible: true,
  },
];

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
  occurred_at: "2026-09-20T00:00:03Z",
};

function envelope(run: RunView = runFixture): WebBiUploadEnvelope {
  return {
    schema_version: "slk.bi.upload/v1",
    bi_version: "1.1.0",
    upload_id: "upload-a",
    generated_at: "2026-10-04T00:00:00Z",
    device: { device_id: "device-a", device_name: "Workstation A" },
    runs: [{ run, messages: [message] }],
  };
}

describe("WebBI upload contract", () => {
  it("accepts only BI 1.1 envelopes with exact catalog types", () => {
    expect(parseUploadEnvelope(envelope(), catalog).runs[0]?.messages).toEqual([
      { ...message, occurred_at: "2026-09-20T00:00:03.000Z" },
    ]);
  });

  it("normalizes upload timestamps before server ordering", () => {
    const input = envelope();
    input.generated_at = "2026-10-04T08:00:00+08:00";
    expect(parseUploadEnvelope(input, catalog).generated_at).toBe("2026-10-04T00:00:00.000Z");
  });

  it("rejects unknown fields instead of permissively expanding WebBI data", () => {
    expect(() =>
      parseUploadEnvelope({ ...envelope(), hidden_logs: ["raw"] }, catalog),
    ).toThrow("SLK_WEBBI_UPLOAD_INVALID");
  });

  it("rejects a role/type mismatch even when a device claims it is valid", () => {
    const invalid = envelope();
    invalid.runs[0]!.messages[0] = { ...message, author_role: "checker" };
    expect(() => parseUploadEnvelope(invalid, catalog)).toThrow(
      "SLK_WEBBI_MESSAGE_ROLE_INVALID",
    );
  });
});

describe("ntfy settings contract", () => {
  it("allows exact message ids and rejects invented categories", () => {
    expect(
      parseNotificationSettingsInput(
        {
          enabled: true,
          server_url: "https://ntfy.example.test",
          topic: "slk",
          auth_mode: "token",
          secret: "private-token",
          selection_mode: "selected",
          selected_message_types: ["EVENT:WORK_STARTED"],
        },
        catalog,
      ).selected_message_types,
    ).toEqual(["EVENT:WORK_STARTED"]);

    expect(() =>
      parseNotificationSettingsInput(
        {
          enabled: true,
          server_url: "https://ntfy.example.test",
          topic: "slk",
          auth_mode: "none",
          selection_mode: "selected",
          selected_message_types: ["进度变化"],
        },
        catalog,
      ),
    ).toThrow("SLK_WEBBI_NOTIFICATION_TYPE_INVALID");
  });

  it("permits an omitted stored secret only when the caller explicitly proves reuse", () => {
    const input = {
      enabled: true,
      server_url: "https://ntfy.example.test",
      topic: "slk",
      auth_mode: "token",
      selection_mode: "all",
      selected_message_types: [],
    };
    expect(() => parseNotificationSettingsInput(input, catalog)).toThrow(
      "SLK_WEBBI_NOTIFICATION_INVALID",
    );
    expect(
      parseNotificationSettingsInput(input, catalog, { allow_secret_reuse: true }),
    ).not.toHaveProperty("secret");
  });
});
