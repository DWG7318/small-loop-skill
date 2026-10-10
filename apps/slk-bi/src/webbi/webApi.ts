import type { MessageCatalogEntry } from "../messages/messageFeed";
import { isCompatibleBiVersion } from "../version";
import type { NotificationSettingsInput } from "./contracts";
import type { PublicNotificationSettings } from "./notifications";
import type { WebBiArchiveRecord } from "./worker";

export interface WebBiApi {
  listRuns(archived: boolean): Promise<WebBiArchiveRecord[]>;
  getRun(deviceId: string, runId: string): Promise<WebBiArchiveRecord>;
  catalog(): Promise<readonly MessageCatalogEntry[]>;
  getNotificationSettings(): Promise<PublicNotificationSettings>;
  saveNotificationSettings(input: NotificationSettingsInput): Promise<PublicNotificationSettings>;
  testNotification(): Promise<void>;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const body = await response.json() as { error?: string } & T;
  if (!response.ok) throw new Error(body.error ?? `SLK_WEBBI_HTTP_${response.status}`);
  return body;
}

export const webBiApi: WebBiApi = {
  async listRuns(archived) {
    const body = await json<{
      schema_version: string;
      bi_version: string;
      runs: WebBiArchiveRecord[];
    }>(`/api/v1/runs?archive=${archived ? "archived" : "active"}`);
    if (body.schema_version !== "slk.webbi.runs/v1" || !isCompatibleBiVersion(body.bi_version) || !Array.isArray(body.runs)) {
      throw new Error("SLK_WEBBI_RESPONSE_INVALID");
    }
    return body.runs;
  },
  async getRun(deviceId, runId) {
    const body = await json<{
      schema_version: string;
      bi_version: string;
      record: WebBiArchiveRecord;
    }>(`/api/v1/runs/${encodeURIComponent(deviceId)}/${encodeURIComponent(runId)}`);
    if (body.schema_version !== "slk.webbi.run/v1" || !isCompatibleBiVersion(body.bi_version) || !body.record) {
      throw new Error("SLK_WEBBI_RESPONSE_INVALID");
    }
    return body.record;
  },
  async catalog() {
    const body = await json<{ schema_version: string; entries: MessageCatalogEntry[] }>(
      "/api/v1/catalog",
    );
    if (body.schema_version !== "slk.bi.message-catalog/v1" || !Array.isArray(body.entries)) {
      throw new Error("SLK_WEBBI_RESPONSE_INVALID");
    }
    return body.entries;
  },
  async getNotificationSettings() {
    return await json<PublicNotificationSettings>("/api/v1/notification-settings");
  },
  async saveNotificationSettings(input) {
    return await json<PublicNotificationSettings>("/api/v1/notification-settings", {
      method: "PUT",
      body: JSON.stringify(input),
    });
  },
  async testNotification() {
    await json("/api/v1/notification-settings/test", {
      method: "POST",
    });
  },
};
