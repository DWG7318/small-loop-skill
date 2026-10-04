import type { RunView } from "../contracts";
import type { AuthoritativeMessage, MessageCatalogEntry } from "../messages/messageFeed";
import {
  parseNotificationSettingsInput,
  parseUploadEnvelope,
  type NotificationSettingsInput,
  type WebBiDevice,
  type WebBiUploadEnvelope,
} from "./contracts";
import {
  notificationKey,
  canReuseNotificationSecret,
  selectMessagesForNotification,
  toPublicNotificationSettings,
  type StoredNotificationSettings,
} from "./notifications";

export interface WebBiArchiveRecord {
  device: WebBiDevice;
  run: RunView;
  messages: AuthoritativeMessage[];
  updated_at: string;
}

export function isArchivedRun(run: RunView) {
  return run.summary.closure_state !== "open"
    || run.summary.state === "archived"
    || Boolean(run.summary.archived_at);
}

export interface IngestedMessage {
  device: WebBiDevice;
  run: RunView;
  message: AuthoritativeMessage;
}

export interface IngestResult {
  bootstrap: boolean;
  inserted_messages: IngestedMessage[];
}

export interface NtfyDeliveryTarget {
  settings: StoredNotificationSettings;
  secret: string | null;
}

export interface WebBiStore {
  ingest(envelope: WebBiUploadEnvelope): Promise<IngestResult>;
  listRuns(archived: boolean): Promise<WebBiArchiveRecord[]>;
  getRun(deviceId: string, runId: string): Promise<WebBiArchiveRecord | null>;
  getSettings(): Promise<StoredNotificationSettings>;
  saveSettings(settings: NotificationSettingsInput): Promise<StoredNotificationSettings>;
  notificationTarget(): Promise<NtfyDeliveryTarget | null>;
  hasDelivery(key: string): Promise<boolean>;
  recordDelivery(key: string, status: "sent" | "failed", error?: string): Promise<void>;
}

export interface WebBiNotifier {
  send(target: NtfyDeliveryTarget, record: IngestedMessage): Promise<void>;
  test(target: NtfyDeliveryTarget): Promise<void>;
}

export interface WebBiHandlerDependencies {
  store: WebBiStore;
  notifier: WebBiNotifier;
  catalog: readonly MessageCatalogEntry[];
  ingest_token: string;
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function bearer(request: Request) {
  const value = request.headers.get("authorization") ?? "";
  return value.startsWith("Bearer ") ? value.slice(7) : "";
}

function bearerAuthorized(request: Request, token: string) {
  return token.length >= 12 && bearer(request) === token;
}

async function requestJson(request: Request) {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(length) && length > 10 * 1024 * 1024) {
    throw new Error("SLK_WEBBI_UPLOAD_TOO_LARGE");
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > 10 * 1024 * 1024) {
    throw new Error("SLK_WEBBI_UPLOAD_TOO_LARGE");
  }
  try { return JSON.parse(body) as unknown; } catch { throw new Error("SLK_WEBBI_JSON_INVALID"); }
}

async function deliverNewMessages(
  dependencies: WebBiHandlerDependencies,
  result: IngestResult,
) {
  if (result.bootstrap || result.inserted_messages.length === 0) return 0;
  const target = await dependencies.store.notificationTarget();
  if (!target?.settings.enabled) return 0;
  const selected = selectMessagesForNotification(
    result.inserted_messages.map(({ message }) => message),
    target.settings,
  );
  const selectedIds = new Set(selected.map(({ message_id }) => message_id));
  let failures = 0;
  for (const record of result.inserted_messages) {
    if (!selectedIds.has(record.message.message_id)) continue;
    const key = notificationKey(
      target.settings.config_version,
      record.device.device_id,
      record.message,
    );
    if (await dependencies.store.hasDelivery(key)) continue;
    try {
      await dependencies.notifier.send(target, record);
      await dependencies.store.recordDelivery(key, "sent");
    } catch (error) {
      failures += 1;
      await dependencies.store.recordDelivery(
        key,
        "failed",
        error instanceof Error ? error.message.slice(0, 256) : "notification failed",
      );
    }
  }
  return failures;
}

export function createWebBiHandler(dependencies: WebBiHandlerDependencies) {
  return async (request: Request): Promise<Response> => {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/api/v1/uploads" && request.method === "POST") {
        if (!bearerAuthorized(request, dependencies.ingest_token)) {
          return json({ error: "SLK_WEBBI_UPLOAD_UNAUTHORIZED" }, 401);
        }
        const envelope = parseUploadEnvelope(await requestJson(request), dependencies.catalog);
        const result = await dependencies.store.ingest(envelope);
        const notification_failures = await deliverNewMessages(dependencies, result);
        return json({
          status: "accepted",
          upload_id: envelope.upload_id,
          inserted_message_count: result.inserted_messages.length,
          historical_bootstrap: result.bootstrap,
          notification_failures,
        }, 202);
      }

      // Run facts stay read-only; notification configuration permits manual editing.
      if (url.pathname === "/api/v1/catalog" && request.method === "GET") {
        return json({ schema_version: "slk.bi.message-catalog/v1", entries: dependencies.catalog });
      }
      if (url.pathname === "/api/v1/runs" && request.method === "GET") {
        const archive = url.searchParams.get("archive") ?? "active";
        if (archive !== "active" && archive !== "archived") {
          return json({ error: "SLK_WEBBI_ARCHIVE_FILTER_INVALID" }, 400);
        }
        return json({
          schema_version: "slk.webbi.runs/v1",
          bi_version: "1.1.0",
          runs: await dependencies.store.listRuns(archive === "archived"),
        });
      }
      const runMatch = url.pathname.match(/^\/api\/v1\/runs\/([^/]+)\/([^/]+)$/);
      if (runMatch && request.method === "GET") {
        const record = await dependencies.store.getRun(
          decodeURIComponent(runMatch[1]!),
          decodeURIComponent(runMatch[2]!),
        );
        return record
          ? json({ schema_version: "slk.webbi.run/v1", bi_version: "1.1.0", record })
          : json({ error: "SLK_WEBBI_RUN_NOT_FOUND" }, 404);
      }
      if (url.pathname === "/api/v1/notification-settings") {
        if (request.method === "GET") {
          return json(toPublicNotificationSettings(await dependencies.store.getSettings()));
        }
        if (request.method === "PUT") {
          const input = await requestJson(request);
          const current = await dependencies.store.getSettings();
          const requestedMode = input && typeof input === "object" && !Array.isArray(input)
            ? (input as Record<string, unknown>).auth_mode
            : undefined;
          const parsed = parseNotificationSettingsInput(input, dependencies.catalog, {
            allow_secret_reuse: requestedMode === current.auth_mode
              && Boolean(current.encrypted_secret && current.secret_iv),
          });
          if (parsed.auth_mode !== "none" && !parsed.secret && !canReuseNotificationSecret(current, parsed)) {
            throw new Error("SLK_WEBBI_NOTIFICATION_SECRET_REQUIRED");
          }
          return json(toPublicNotificationSettings(await dependencies.store.saveSettings(parsed)));
        }
      }
      if (url.pathname === "/api/v1/notification-settings/test" && request.method === "POST") {
        const target = await dependencies.store.notificationTarget();
        if (!target) return json({ error: "SLK_WEBBI_NOTIFICATION_NOT_CONFIGURED" }, 409);
        await dependencies.notifier.test(target);
        return json({ status: "sent" });
      }
      return json({ error: "SLK_WEBBI_ROUTE_NOT_FOUND" }, 404);
    } catch (error) {
      const code = error instanceof Error ? error.message : "SLK_WEBBI_REQUEST_FAILED";
      return json({ error: code }, code.includes("TOO_LARGE") ? 413 : 400);
    }
  };
}
