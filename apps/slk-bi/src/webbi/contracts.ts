import { parseRunProjection, type RunView } from "../contracts";
import { catalogEntry, catalogKey } from "../messages/catalog";
import type {
  AuthoritativeMessage,
  MessageCatalogEntry,
  MessageSourceKind,
  SlkRole,
} from "../messages/messageFeed";

type UnknownObject = Record<string, unknown>;

export interface WebBiDevice {
  device_id: string;
  device_name: string;
}

export interface WebBiRunUpload {
  run: RunView;
  messages: AuthoritativeMessage[];
}

export interface WebBiUploadEnvelope {
  schema_version: "slk.bi.upload/v1";
  bi_version: "1.1.0";
  upload_id: string;
  generated_at: string;
  device: WebBiDevice;
  runs: WebBiRunUpload[];
}

export type NtfyAuthMode = "none" | "token" | "password";
export type NotificationSelectionMode = "all" | "selected";

export interface NotificationSettingsInput {
  enabled: boolean;
  server_url: string;
  topic: string;
  auth_mode: NtfyAuthMode;
  username?: string | null;
  secret?: string;
  selection_mode: NotificationSelectionMode;
  selected_message_types: string[];
}

function object(value: unknown, code: string): UnknownObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(code);
  return value as UnknownObject;
}

function exactKeys(value: UnknownObject, expected: readonly string[], code: string) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new Error(code);
  }
}

function text(value: unknown, max: number, code: string) {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error(code);
  return value;
}

function optionalText(value: unknown, max: number, code: string) {
  if (value === undefined || value === null || value === "") return undefined;
  return text(value, max, code);
}

function iso(value: unknown, code: string) {
  const result = text(value, 64, code);
  const timestamp = Date.parse(result);
  if (Number.isNaN(timestamp)) throw new Error(code);
  return new Date(timestamp).toISOString();
}

function parseMessage(
  value: unknown,
  runId: string,
  catalog: readonly MessageCatalogEntry[],
): AuthoritativeMessage {
  const raw = object(value, "SLK_WEBBI_MESSAGE_INVALID");
  exactKeys(raw, [
    "message_id", "run_id", "source_kind", "source_id", "message_type", "label_zh",
    "author_role", "author_identity_ref", "go_id", "cell_id", "attempt", "occurred_at",
  ], "SLK_WEBBI_MESSAGE_INVALID");
  const sourceKind = text(raw.source_kind, 32, "SLK_WEBBI_MESSAGE_INVALID") as MessageSourceKind;
  if (sourceKind !== "EVENT" && sourceKind !== "OW_OBSERVATION") {
    throw new Error("SLK_WEBBI_MESSAGE_TYPE_INVALID");
  }
  const messageType = text(raw.message_type, 96, "SLK_WEBBI_MESSAGE_TYPE_INVALID");
  const entry = catalogEntry(catalog, sourceKind, messageType);
  if (!entry) throw new Error("SLK_WEBBI_MESSAGE_TYPE_INVALID");
  const role = text(raw.author_role, 32, "SLK_WEBBI_MESSAGE_ROLE_INVALID") as SlkRole;
  if (!entry.allowed_roles.includes(role)) throw new Error("SLK_WEBBI_MESSAGE_ROLE_INVALID");
  if (raw.run_id !== runId) throw new Error("SLK_WEBBI_MESSAGE_SCOPE_INVALID");
  if (raw.label_zh !== entry.label_zh) throw new Error("SLK_WEBBI_MESSAGE_LABEL_INVALID");
  const messageId = text(raw.message_id, 196, "SLK_WEBBI_MESSAGE_INVALID");
  const sourceId = text(raw.source_id, 160, "SLK_WEBBI_MESSAGE_INVALID");
  if (messageId !== `${sourceKind}:${sourceId}`) throw new Error("SLK_WEBBI_MESSAGE_ID_INVALID");
  const attempt = raw.attempt;
  if (attempt !== null && (!Number.isSafeInteger(attempt) || Number(attempt) < 1)) {
    throw new Error("SLK_WEBBI_MESSAGE_SCOPE_INVALID");
  }
  return {
    message_id: messageId,
    run_id: runId,
    source_kind: sourceKind,
    source_id: sourceId,
    message_type: messageType,
    label_zh: entry.label_zh,
    author_role: role,
    author_identity_ref: text(raw.author_identity_ref, 160, "SLK_WEBBI_MESSAGE_INVALID"),
    go_id: raw.go_id === null ? null : text(raw.go_id, 96, "SLK_WEBBI_MESSAGE_SCOPE_INVALID"),
    cell_id: raw.cell_id === null ? null : text(raw.cell_id, 96, "SLK_WEBBI_MESSAGE_SCOPE_INVALID"),
    attempt: attempt as number | null,
    occurred_at: iso(raw.occurred_at, "SLK_WEBBI_MESSAGE_INVALID"),
  };
}

export function parseUploadEnvelope(
  value: unknown,
  catalog: readonly MessageCatalogEntry[],
): WebBiUploadEnvelope {
  const raw = object(value, "SLK_WEBBI_UPLOAD_INVALID");
  exactKeys(
    raw,
    ["schema_version", "bi_version", "upload_id", "generated_at", "device", "runs"],
    "SLK_WEBBI_UPLOAD_INVALID",
  );
  if (raw.schema_version !== "slk.bi.upload/v1" || raw.bi_version !== "1.1.0") {
    throw new Error("SLK_WEBBI_UPLOAD_VERSION_UNSUPPORTED");
  }
  const deviceRaw = object(raw.device, "SLK_WEBBI_DEVICE_INVALID");
  exactKeys(deviceRaw, ["device_id", "device_name"], "SLK_WEBBI_DEVICE_INVALID");
  const device = {
    device_id: text(deviceRaw.device_id, 128, "SLK_WEBBI_DEVICE_INVALID"),
    device_name: text(deviceRaw.device_name, 128, "SLK_WEBBI_DEVICE_INVALID"),
  };
  if (!Array.isArray(raw.runs) || raw.runs.length > 500) {
    throw new Error("SLK_WEBBI_UPLOAD_INVALID");
  }
  const runs = raw.runs.map((item) => {
    const runRaw = object(item, "SLK_WEBBI_UPLOAD_INVALID");
    exactKeys(runRaw, ["run", "messages"], "SLK_WEBBI_UPLOAD_INVALID");
    const run = parseRunProjection(runRaw.run);
    if (!Array.isArray(runRaw.messages) || runRaw.messages.length > 50_000) {
      throw new Error("SLK_WEBBI_UPLOAD_INVALID");
    }
    const messages = runRaw.messages.map((message) => parseMessage(message, run.run_id, catalog));
    if (new Set(messages.map((message) => message.message_id)).size !== messages.length) {
      throw new Error("SLK_WEBBI_MESSAGE_DUPLICATE");
    }
    return { run, messages };
  });
  if (new Set(runs.map(({ run }) => run.run_id)).size !== runs.length) {
    throw new Error("SLK_WEBBI_RUN_DUPLICATE");
  }
  return {
    schema_version: "slk.bi.upload/v1",
    bi_version: "1.1.0",
    upload_id: text(raw.upload_id, 160, "SLK_WEBBI_UPLOAD_INVALID"),
    generated_at: iso(raw.generated_at, "SLK_WEBBI_UPLOAD_INVALID"),
    device,
    runs,
  };
}

export function parseNotificationSettingsInput(
  value: unknown,
  catalog: readonly MessageCatalogEntry[],
  options: { allow_secret_reuse?: boolean } = {},
): NotificationSettingsInput {
  const raw = object(value, "SLK_WEBBI_NOTIFICATION_INVALID");
  const allowedKeys = [
    "enabled", "server_url", "topic", "auth_mode", "username", "secret",
    "selection_mode", "selected_message_types",
  ];
  if (Object.keys(raw).some((key) => !allowedKeys.includes(key))) {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  if (typeof raw.enabled !== "boolean") throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  const serverUrl = text(raw.server_url, 512, "SLK_WEBBI_NOTIFICATION_INVALID");
  let url: URL;
  try { url = new URL(serverUrl); } catch { throw new Error("SLK_WEBBI_NOTIFICATION_INVALID"); }
  if (url.protocol !== "https:" && url.hostname !== "localhost") {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  const topic = text(raw.topic, 128, "SLK_WEBBI_NOTIFICATION_INVALID");
  if (!/^[A-Za-z0-9_-]+$/.test(topic)) throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  if (!(["none", "token", "password"] as const).includes(raw.auth_mode as NtfyAuthMode)) {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  if (!(["all", "selected"] as const).includes(raw.selection_mode as NotificationSelectionMode)) {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  if (!Array.isArray(raw.selected_message_types)) {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  const validKeys = new Set(
    catalog.filter((entry) => entry.notification_eligible)
      .map((entry) => catalogKey(entry.source_kind, entry.message_type)),
  );
  const selected = raw.selected_message_types.map((item) =>
    text(item, 160, "SLK_WEBBI_NOTIFICATION_TYPE_INVALID"));
  if (selected.some((item) => !validKeys.has(item))) {
    throw new Error("SLK_WEBBI_NOTIFICATION_TYPE_INVALID");
  }
  const authMode = raw.auth_mode as NtfyAuthMode;
  const username = optionalText(raw.username, 256, "SLK_WEBBI_NOTIFICATION_INVALID");
  const secret = optionalText(raw.secret, 4096, "SLK_WEBBI_NOTIFICATION_INVALID");
  if (authMode === "password" && !username) throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  if (authMode !== "none" && !secret && !options.allow_secret_reuse) {
    throw new Error("SLK_WEBBI_NOTIFICATION_INVALID");
  }
  return {
    enabled: raw.enabled,
    server_url: url.toString().replace(/\/$/, ""),
    topic,
    auth_mode: authMode,
    username: username ?? null,
    ...(secret ? { secret } : {}),
    selection_mode: raw.selection_mode as NotificationSelectionMode,
    selected_message_types: [...new Set(selected)].sort(),
  };
}
