import { describe, expect, it } from "vitest";

import { MESSAGE_CATALOG } from "../messages/catalog";
import type { AuthoritativeMessage } from "../messages/messageFeed";
import { runFixture } from "../test/fixtures";
import type { WebBiUploadEnvelope } from "./contracts";
import type {
  IngestResult,
  NtfyDeliveryTarget,
  WebBiArchiveRecord,
  WebBiStore,
  WebBiNotifier,
} from "./worker";
import { createWebBiHandler } from "./worker";
import { isArchivedRun } from "./worker";
import type { StoredNotificationSettings } from "./notifications";

const workerMessage: AuthoritativeMessage = {
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

function upload(deviceId: string, messages = [workerMessage]): WebBiUploadEnvelope {
  return {
    schema_version: "slk.bi.upload/v1",
    bi_version: "1.1.0",
    upload_id: `${deviceId}-upload`,
    generated_at: "2026-10-04T00:00:00Z",
    device: { device_id: deviceId, device_name: `Computer ${deviceId}` },
    runs: [{ run: runFixture, messages }],
  };
}

class MemoryStore implements WebBiStore {
  devices = new Set<string>();
  messages = new Set<string>();
  records = new Map<string, WebBiArchiveRecord>();
  deliveries = new Set<string>();
  settings: StoredNotificationSettings = {
    enabled: true,
    server_url: "https://ntfy.example.test",
    topic: "slk",
    auth_mode: "none",
    username: null,
    encrypted_secret: null,
    secret_iv: null,
    selection_mode: "all",
    selected_message_types: [],
    config_version: 1,
  };

  async ingest(envelope: WebBiUploadEnvelope): Promise<IngestResult> {
    const bootstrap = !this.devices.has(envelope.device.device_id);
    this.devices.add(envelope.device.device_id);
    const inserted_messages: IngestResult["inserted_messages"] = [];
    for (const item of envelope.runs) {
      const key = `${envelope.device.device_id}:${item.run.run_id}`;
      this.records.set(key, {
        device: envelope.device,
        run: item.run,
        messages: item.messages,
        updated_at: envelope.generated_at,
      });
      for (const message of item.messages) {
        const messageKey = `${envelope.device.device_id}:${message.message_id}`;
        if (!this.messages.has(messageKey)) {
          this.messages.add(messageKey);
          inserted_messages.push({
            device: envelope.device,
            run: item.run,
            message,
          });
        }
      }
    }
    return { bootstrap, inserted_messages };
  }

  async listRuns(archived: boolean) {
    return [...this.records.values()].filter((record) =>
      Boolean(record.run.summary.archived_at) === archived);
  }

  async getRun(deviceId: string, runId: string) {
    return this.records.get(`${deviceId}:${runId}`) ?? null;
  }

  async getSettings() { return this.settings; }
  async saveSettings(input: Parameters<WebBiStore["saveSettings"]>[0]) {
    this.settings = {
      ...this.settings,
      ...input,
      username: input.username ?? null,
      config_version: this.settings.config_version + 1,
    };
    return this.settings;
  }
  async notificationTarget(): Promise<NtfyDeliveryTarget | null> {
    return { settings: this.settings, secret: null };
  }
  async hasDelivery(key: string) { return this.deliveries.has(key); }
  async recordDelivery(key: string) { this.deliveries.add(key); }
}

class RecordingNotifier implements WebBiNotifier {
  sent: string[] = [];
  async send(_target: NtfyDeliveryTarget, record: IngestResult["inserted_messages"][number]) {
    this.sent.push(`${record.device.device_id}:${record.message.message_id}`);
  }
  async test() { this.sent.push("test"); }
}

function request(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  return new Request(`https://slk.example.test${path}`, { ...init, headers });
}

describe("WebBI worker", () => {
  it("reads existing Run details and redacted settings publicly without changing state", async () => {
    const store = new MemoryStore();
    await store.ingest(upload("device-a"));
    store.settings = { ...store.settings, encrypted_secret: "ciphertext", secret_iv: "iv" };
    const notifier = new RecordingNotifier();
    const handler = createWebBiHandler({
      store, notifier, catalog: MESSAGE_CATALOG,
      ingest_token: "ingest-secret",
    });
    const before = JSON.stringify(store.settings);
    const detail = await handler(new Request("https://slk.example.test/api/v1/runs/device-a/run-a"));
    expect(detail.status).toBe(200);
    expect(await detail.json()).toMatchObject({ record: { run: { run_id: "run-a" } } });
    const settings = await handler(new Request("https://slk.example.test/api/v1/notification-settings"));
    expect(settings.status).toBe(200);
    expect(await settings.text()).not.toContain("ciphertext");
    const rejected = await handler(new Request("https://slk.example.test/api/v1/notification-settings", {
      method: "PUT", body: "{}",
    }));
    expect(rejected.status).toBe(400);
    expect(JSON.stringify(store.settings)).toBe(before);
    expect(store.records.size).toBe(1);
    expect(notifier.sent).toEqual([]);
  });

  it("saves settings and sends a test without a management credential or Run mutation", async () => {
    const store = new MemoryStore();
    const notifier = new RecordingNotifier();
    const handler = createWebBiHandler({
      store, notifier, catalog: MESSAGE_CATALOG, ingest_token: "ingest-secret",
    });
    const saved = await handler(new Request("https://slk.example.test/api/v1/notification-settings", {
      method: "PUT", body: JSON.stringify({
        enabled: true, server_url: store.settings.server_url, topic: "owner-alerts",
        auth_mode: "none", selection_mode: "all", selected_message_types: [],
      }),
    }));
    expect(saved.status).toBe(200);
    expect(await saved.json()).toMatchObject({ topic: "owner-alerts", config_version: 2 });
    const accepted = await handler(new Request("https://slk.example.test/api/v1/notification-settings/test", { method: "POST" }));
    expect(accepted.status).toBe(200);
    expect(notifier.sent).toEqual(["test"]);
    expect(store.records.size).toBe(0);
    expect(store.settings.config_version).toBe(2);
  });

  it.each([
    { server_url: "https://another.example.test", username: "owner" },
    { server_url: "https://ntfy.example.test", username: "another-user" },
  ])("does not forward a retained ntfy password to a changed destination/account: %o", async (change) => {
    const store = new MemoryStore();
    store.settings = { ...store.settings, auth_mode: "password", username: "owner", encrypted_secret: "ciphertext", secret_iv: "iv" };
    const before = JSON.stringify(store.settings);
    const handler = createWebBiHandler({ store, notifier: new RecordingNotifier(), catalog: MESSAGE_CATALOG, ingest_token: "ingest-secret" });
    const response = await handler(request("/api/v1/notification-settings", {
      method: "PUT", body: JSON.stringify({
        enabled: true, topic: "slk", auth_mode: "password", selection_mode: "all", selected_message_types: [], ...change,
      }),
    }));
    expect(response.status).toBe(400);
    expect(JSON.stringify(store.settings)).toBe(before);
  });

  it("treats every terminal Run as archived even before an archived_at timestamp is present", () => {
    expect(isArchivedRun({
      ...runFixture,
      summary: { ...runFixture.summary, closure_state: "closed", archived_at: null },
    })).toBe(true);
    expect(isArchivedRun(runFixture)).toBe(false);
  });

  it("keeps identical Run ids isolated by device and preserves archive records", async () => {
    const store = new MemoryStore();
    const handler = createWebBiHandler({
      store,
      notifier: new RecordingNotifier(),
      catalog: MESSAGE_CATALOG,
      ingest_token: "ingest-secret",
    });
    for (const deviceId of ["device-a", "device-b"]) {
      await handler(request("/api/v1/uploads", {
        method: "POST",
        headers: { authorization: "Bearer ingest-secret" },
        body: JSON.stringify(upload(deviceId)),
      }));
    }
    const response = await handler(request("/api/v1/runs?archive=active"));
    const body = await response.json() as { runs: WebBiArchiveRecord[] };
    expect(body.runs.map((record) => record.device.device_id).sort()).toEqual([
      "device-a",
      "device-b",
    ]);
  });

  it("keeps first upload silent and sends one notification for one later new message", async () => {
    const store = new MemoryStore();
    const notifier = new RecordingNotifier();
    const handler = createWebBiHandler({
      store,
      notifier,
      catalog: MESSAGE_CATALOG,
      ingest_token: "ingest-secret",
    });
    const post = (body: WebBiUploadEnvelope) => handler(request("/api/v1/uploads", {
      method: "POST",
      headers: { authorization: "Bearer ingest-secret" },
      body: JSON.stringify(body),
    }));
    await post(upload("device-a"));
    expect(notifier.sent).toEqual([]);

    const second = {
      ...workerMessage,
      message_id: "EVENT:work-progress",
      source_id: "work-progress",
      message_type: "WORK_PROGRESS",
      label_zh: "Worker 记录进展",
    };
    await post(upload("device-a", [workerMessage, second]));
    await post(upload("device-a", [workerMessage, second]));
    expect(notifier.sent).toEqual(["device-a:EVENT:work-progress"]);
  });

  it("requires upload authentication and never exposes stored notification secrets", async () => {
    const store = new MemoryStore();
    store.settings = { ...store.settings, encrypted_secret: "ciphertext", secret_iv: "iv" };
    const handler = createWebBiHandler({
      store,
      notifier: new RecordingNotifier(),
      catalog: MESSAGE_CATALOG,
      ingest_token: "ingest-secret",
    });
    const denied = await handler(request("/api/v1/uploads", {
      method: "POST",
      headers: { authorization: "Bearer wrong" },
      body: JSON.stringify(upload("device-a")),
    }));
    expect(denied.status).toBe(401);

    const settings = await handler(request("/api/v1/notification-settings"));
    const raw = await settings.text();
    expect(raw).not.toContain("ciphertext");
    expect(raw).not.toContain('"secret"');
    expect(JSON.parse(raw).has_secret).toBe(true);
  });

  it("preserves an existing ntfy secret but rejects a missing secret for a new auth mode", async () => {
    const store = new MemoryStore();
    store.settings = {
      ...store.settings,
      auth_mode: "token",
      encrypted_secret: "ciphertext",
      secret_iv: "iv",
    };
    const handler = createWebBiHandler({
      store,
      notifier: new RecordingNotifier(),
      catalog: MESSAGE_CATALOG,
      ingest_token: "ingest-secret",
    });
    const keep = await handler(request("/api/v1/notification-settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: true,
        server_url: "https://ntfy.example.test",
        topic: "slk-alerts",
        auth_mode: "token",
        selection_mode: "all",
        selected_message_types: [],
      }),
    }));
    expect(keep.status).toBe(200);

    const change = await handler(request("/api/v1/notification-settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: true,
        server_url: "https://ntfy.example.test",
        topic: "slk-alerts",
        auth_mode: "password",
        username: "owner",
        selection_mode: "all",
        selected_message_types: [],
      }),
    }));
    expect(change.status).toBe(400);
    expect(await change.json()).toEqual({ error: "SLK_WEBBI_NOTIFICATION_INVALID" });
  });
});
