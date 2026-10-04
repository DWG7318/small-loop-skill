// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { D1WebBiStore, type D1Database } from "./d1Store";
import type { NotificationSettingsInput } from "./contracts";

function fixture() {
  const row = {
    enabled: 1, server_url: "https://ntfy.example.test", topic: "slk",
    auth_mode: "password", username: "owner", encrypted_secret: "ciphertext", secret_iv: "iv",
    selection_mode: "all", selected_message_types_json: "[]", config_version: 1,
  };
  const write = vi.fn(async () => ({ success: true, results: [] }));
  const bind = vi.fn();
  const statement = {
    bind(...values: unknown[]) { bind(...values); return this; },
    first: async () => row,
    all: async () => ({ success: true, results: [] }),
    run: write,
  };
  const database = { prepare: () => statement } as unknown as D1Database;
  const input: NotificationSettingsInput = {
    enabled: true, server_url: row.server_url, topic: "owner-alerts",
    auth_mode: "password", username: "owner", selection_mode: "all", selected_message_types: [],
  };
  return { store: new D1WebBiStore(database, "unused-for-reuse"), write, bind, input };
}

describe("WebBI stored ntfy credential scope", () => {
  it.each([
    { server_url: "https://another.example.test" },
    { username: "another-user" },
  ])("requires a new credential when the destination/account changes: %o", async (change) => {
    const { store, write, input } = fixture();
    await expect(store.saveSettings({ ...input, ...change })).rejects.toThrow("SLK_WEBBI_NOTIFICATION_SECRET_REQUIRED");
    expect(write).not.toHaveBeenCalled();
  });

  it("keeps an encrypted credential for an unchanged server/account when editing the topic", async () => {
    const { store, write, bind, input } = fixture();
    await store.saveSettings(input);
    expect(write).toHaveBeenCalledOnce();
    expect(bind).toHaveBeenCalledWith(1, input.server_url, input.topic, "password", "owner", "ciphertext", "iv", "all", "[]", 2, expect.any(String));
  });
});
