import type { AuthoritativeMessage } from "../messages/messageFeed";
import type { RunView } from "../contracts";
import { canonicalJson, canonicalSummary, sha256 } from "../closeout";
import type { NotificationSettingsInput, WebBiUploadEnvelope } from "./contracts";
import type {
  IngestResult,
  NtfyDeliveryTarget,
  WebBiArchiveRecord,
  WebBiStore,
} from "./worker";
import { isArchivedRun } from "./worker";
import { canReuseNotificationSecret, type StoredNotificationSettings } from "./notifications";

export interface D1Result<T = unknown> {
  results: T[];
  success: boolean;
  meta?: { changes?: number };
}

export interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  all<T = Record<string, unknown>>(): Promise<D1Result<T>>;
  run<T = Record<string, unknown>>(): Promise<D1Result<T>>;
}

export interface D1Database {
  prepare(query: string): D1PreparedStatement;
}

interface RunRow {
  device_id: string;
  device_name: string;
  run_id: string;
  payload_json: string;
  updated_at: string;
  source_generated_at: string | null;
}

interface MessageRow {
  payload_json: string;
}

interface SettingsRow {
  enabled: number;
  server_url: string;
  topic: string;
  auth_mode: StoredNotificationSettings["auth_mode"];
  username: string | null;
  encrypted_secret: string | null;
  secret_iv: string | null;
  selection_mode: StoredNotificationSettings["selection_mode"];
  selected_message_types_json: string;
  config_version: number;
}

function bytesToBase64(bytes: Uint8Array) {
  let value = "";
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value);
}

function base64ToBytes(value: string) {
  try {
    const decoded = atob(value);
    return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  } catch {
    throw new Error("SLK_WEBBI_ENCRYPTION_KEY_INVALID");
  }
}

async function encryptionKey(encoded: string) {
  const raw = base64ToBytes(encoded);
  if (raw.byteLength !== 32) throw new Error("SLK_WEBBI_ENCRYPTION_KEY_INVALID");
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptSecret(secret: string, encodedKey: string) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await encryptionKey(encodedKey),
    new TextEncoder().encode(secret),
  );
  return {
    encrypted_secret: bytesToBase64(new Uint8Array(ciphertext)),
    secret_iv: bytesToBase64(iv),
  };
}

async function decryptSecret(ciphertext: string, iv: string, encodedKey: string) {
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(iv) },
      await encryptionKey(encodedKey),
      base64ToBytes(ciphertext),
    );
    return new TextDecoder().decode(plaintext);
  } catch {
    throw new Error("SLK_WEBBI_NOTIFICATION_SECRET_UNAVAILABLE");
  }
}

function settingsFrom(row: SettingsRow | null): StoredNotificationSettings {
  if (!row) {
    return {
      enabled: false,
      server_url: "https://ntfy.sh",
      topic: "slk",
      auth_mode: "none",
      username: null,
      encrypted_secret: null,
      secret_iv: null,
      selection_mode: "selected",
      selected_message_types: [],
      config_version: 0,
    };
  }
  const selected = JSON.parse(row.selected_message_types_json) as unknown;
  if (!Array.isArray(selected) || selected.some((item) => typeof item !== "string")) {
    throw new Error("SLK_WEBBI_NOTIFICATION_SETTINGS_CORRUPT");
  }
  return {
    enabled: row.enabled === 1,
    server_url: row.server_url,
    topic: row.topic,
    auth_mode: row.auth_mode,
    username: row.username,
    encrypted_secret: row.encrypted_secret,
    secret_iv: row.secret_iv,
    selection_mode: row.selection_mode,
    selected_message_types: selected,
    config_version: row.config_version,
  };
}

export class D1WebBiStore implements WebBiStore {
  constructor(
    private readonly database: D1Database,
    private readonly settingsEncryptionKey: string,
  ) {}

  async ingest(envelope: WebBiUploadEnvelope): Promise<IngestResult> {
    const device = await this.database
      .prepare("SELECT device_id FROM devices WHERE device_id=?1")
      .bind(envelope.device.device_id)
      .first<{ device_id: string }>();
    const bootstrap = device === null;
    await this.database.prepare(
      `INSERT INTO devices(device_id,device_name,registered_at,last_seen_at)
       VALUES(?1,?2,?3,?3)
       ON CONFLICT(device_id) DO UPDATE SET device_name=excluded.device_name,last_seen_at=excluded.last_seen_at
       WHERE excluded.last_seen_at > devices.last_seen_at`,
    ).bind(
      envelope.device.device_id,
      envelope.device.device_name,
      envelope.generated_at,
    ).run();

    const inserted_messages: IngestResult["inserted_messages"] = [];
    const receipts: IngestResult["receipts"] = [];
    for (const item of envelope.runs) {
      let error: string | undefined;
      let stored: WebBiArchiveRecord | null = null;
      try {
        const incoming = item.run.closeout_summary;
        if (incoming && await sha256(canonicalSummary(incoming)) !== incoming.content_sha256) throw new Error("SLK_WEBBI_SUMMARY_HASH_INVALID");
        // Compare-and-swap prevents simultaneous requests from overwriting a newer summary.
        for (let attempt = 0; attempt < 8; attempt += 1) {
          const previous = await this.getRun(envelope.device.device_id, item.run.run_id);
          const old = previous?.run.closeout_summary;
          if (old && incoming && incoming.source_revision === old.source_revision && incoming.content_sha256 !== old.content_sha256) throw new Error("SLK_WEBBI_SUMMARY_REVISION_CONFLICT");
          const staleSummary = old && incoming && incoming.source_revision < old.source_revision;
          const replaceFacts = !previous || (!staleSummary && (!isArchivedRun(previous.run) || isArchivedRun(item.run)) && envelope.generated_at > (previous.source_generated_at ?? previous.updated_at));
          const next: RunView = structuredClone(replaceFacts ? item.run : previous!.run);
          if (previous?.run.device_signature && !next.device_signature) next.device_signature = previous.run.device_signature;
          if (old && (!incoming || incoming.source_revision <= old.source_revision)) next.closeout_summary = old;
          if (incoming && (!old || incoming.source_revision > old.source_revision)) {
            next.closeout_summary = incoming;
            if (item.run.device_signature) next.device_signature = item.run.device_signature;
          }
          if (previous && canonicalJson(previous.run) === canonicalJson(next)) { stored = previous; break; }
          const write = await this.database.prepare(
        `INSERT INTO runs(device_id,run_id,archived,payload_json,updated_at,source_generated_at)
         VALUES(?1,?2,?3,?4,?5,?7)
         ON CONFLICT(device_id,run_id) DO UPDATE SET
           archived=excluded.archived,payload_json=excluded.payload_json,updated_at=excluded.updated_at,source_generated_at=excluded.source_generated_at
         WHERE runs.payload_json=?6`,
      ).bind(
        envelope.device.device_id,
        item.run.run_id,
        isArchivedRun(next) ? 1 : 0,
        JSON.stringify(next),
        new Date().toISOString(),
        previous ? JSON.stringify(previous.run) : null,
        replaceFacts ? envelope.generated_at : previous?.source_generated_at ?? previous?.updated_at ?? envelope.generated_at,
      ).run();
          if (!write.success) throw new Error("SLK_WEBBI_STORE_FAILED");
          if ((write.meta?.changes ?? 0) > 0) { stored = await this.getRun(envelope.device.device_id, item.run.run_id); break; }
        }
        if (!stored) throw new Error("SLK_WEBBI_STORE_BUSY");
      } catch (reason) { error = reason instanceof Error ? reason.message : "SLK_WEBBI_STORE_FAILED"; }
      stored ??= await this.getRun(envelope.device.device_id, item.run.run_id);
      const summary = stored?.run.closeout_summary;
      receipts.push({ device_id: envelope.device.device_id, run_id: item.run.run_id,
        payload_sha256: stored ? await sha256(canonicalJson(stored.run)) : "",
        archived: stored ? isArchivedRun(stored.run) : false, source_id: summary?.source_id ?? null,
        source_revision: summary?.source_revision ?? null, content_sha256: summary?.content_sha256 ?? null,
        saved_at: stored?.updated_at ?? "", ...(error ? { error } : {}) });
      if (error) continue;
      for (const message of item.messages) {
        const result = await this.database.prepare(
          `INSERT OR IGNORE INTO messages
           (device_id,message_id,run_id,source_kind,message_type,payload_json,occurred_at,ingested_at)
           VALUES(?1,?2,?3,?4,?5,?6,?7,?8)`,
        ).bind(
          envelope.device.device_id,
          message.message_id,
          message.run_id,
          message.source_kind,
          message.message_type,
          JSON.stringify(message),
          message.occurred_at,
          envelope.generated_at,
        ).run();
        if ((result.meta?.changes ?? 0) > 0) {
          inserted_messages.push({ device: envelope.device, run: item.run, message });
        }
      }
    }
    return { bootstrap, inserted_messages, receipts };
  }

  private async messages(deviceId: string, runId: string) {
    const rows = await this.database.prepare(
      `SELECT payload_json FROM messages WHERE device_id=?1 AND run_id=?2
       ORDER BY occurred_at,message_id`,
    ).bind(deviceId, runId).all<MessageRow>();
    return rows.results.map(({ payload_json }) => JSON.parse(payload_json) as AuthoritativeMessage);
  }

  private async record(row: RunRow): Promise<WebBiArchiveRecord> {
    return {
      device: { device_id: row.device_id, device_name: row.device_name },
      run: JSON.parse(row.payload_json) as WebBiArchiveRecord["run"],
      messages: await this.messages(row.device_id, row.run_id),
      updated_at: row.updated_at,
      source_generated_at: row.source_generated_at ?? row.updated_at,
    };
  }

  async listRuns(archived: boolean) {
    const rows = await this.database.prepare(
      `SELECT r.device_id,d.device_name,r.run_id,r.payload_json,r.updated_at,r.source_generated_at
       FROM runs r JOIN devices d ON d.device_id=r.device_id
       WHERE r.archived=?1 ORDER BY r.updated_at DESC,r.device_id,r.run_id`,
    ).bind(archived ? 1 : 0).all<RunRow>();
    return Promise.all(rows.results.map((row) => this.record(row)));
  }

  async getRun(deviceId: string, runId: string) {
    const row = await this.database.prepare(
      `SELECT r.device_id,d.device_name,r.run_id,r.payload_json,r.updated_at,r.source_generated_at
       FROM runs r JOIN devices d ON d.device_id=r.device_id
       WHERE r.device_id=?1 AND r.run_id=?2`,
    ).bind(deviceId, runId).first<RunRow>();
    return row ? this.record(row) : null;
  }

  async getSettings() {
    return settingsFrom(await this.database.prepare(
      `SELECT enabled,server_url,topic,auth_mode,username,encrypted_secret,secret_iv,
              selection_mode,selected_message_types_json,config_version
       FROM notification_settings WHERE singleton=1`,
    ).first<SettingsRow>());
  }

  async saveSettings(input: NotificationSettingsInput) {
    const current = await this.getSettings();
    let encrypted_secret: string | null = null;
    let secret_iv: string | null = null;
    if (input.auth_mode !== "none") {
      if (input.secret) {
        ({ encrypted_secret, secret_iv } = await encryptSecret(
          input.secret,
          this.settingsEncryptionKey,
        ));
      } else if (canReuseNotificationSecret(current, input)) {
        encrypted_secret = current.encrypted_secret;
        secret_iv = current.secret_iv;
      } else {
        throw new Error("SLK_WEBBI_NOTIFICATION_SECRET_REQUIRED");
      }
    }
    const version = current.config_version + 1;
    await this.database.prepare(
      `INSERT INTO notification_settings
       (singleton,enabled,server_url,topic,auth_mode,username,encrypted_secret,secret_iv,
        selection_mode,selected_message_types_json,config_version,updated_at)
       VALUES(1,?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)
       ON CONFLICT(singleton) DO UPDATE SET
        enabled=excluded.enabled,server_url=excluded.server_url,topic=excluded.topic,
        auth_mode=excluded.auth_mode,username=excluded.username,
        encrypted_secret=excluded.encrypted_secret,secret_iv=excluded.secret_iv,
        selection_mode=excluded.selection_mode,
        selected_message_types_json=excluded.selected_message_types_json,
        config_version=excluded.config_version,updated_at=excluded.updated_at`,
    ).bind(
      input.enabled ? 1 : 0,
      input.server_url,
      input.topic,
      input.auth_mode,
      input.username ?? null,
      encrypted_secret,
      secret_iv,
      input.selection_mode,
      JSON.stringify(input.selected_message_types),
      version,
      new Date().toISOString(),
    ).run();
    return this.getSettings();
  }

  async notificationTarget(): Promise<NtfyDeliveryTarget | null> {
    const settings = await this.getSettings();
    if (!settings.enabled) return null;
    const secret = settings.encrypted_secret && settings.secret_iv
      ? await decryptSecret(
          settings.encrypted_secret,
          settings.secret_iv,
          this.settingsEncryptionKey,
        )
      : null;
    return { settings, secret };
  }

  async hasDelivery(key: string) {
    const row = await this.database.prepare(
      "SELECT status FROM notification_deliveries WHERE delivery_key=?1",
    ).bind(key).first<{ status: string }>();
    return row?.status === "sent";
  }

  async recordDelivery(key: string, status: "sent" | "failed", error?: string) {
    await this.database.prepare(
      `INSERT INTO notification_deliveries(delivery_key,status,error,attempted_at)
       VALUES(?1,?2,?3,?4)
       ON CONFLICT(delivery_key) DO UPDATE SET
         status=excluded.status,error=excluded.error,attempted_at=excluded.attempted_at`,
    ).bind(key, status, error ?? null, new Date().toISOString()).run();
  }
}
