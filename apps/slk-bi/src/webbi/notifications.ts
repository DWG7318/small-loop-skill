import { catalogKey } from "../messages/catalog";
import type { AuthoritativeMessage } from "../messages/messageFeed";
import type { NotificationSelectionMode, NotificationSettingsInput, NtfyAuthMode } from "./contracts";

export interface NotificationSelection {
  selection_mode: NotificationSelectionMode;
  selected_message_types: string[];
}

export interface StoredNotificationSettings extends NotificationSelection {
  enabled: boolean;
  server_url: string;
  topic: string;
  auth_mode: NtfyAuthMode;
  username: string | null;
  encrypted_secret: string | null;
  secret_iv: string | null;
  config_version: number;
}

export interface PublicNotificationSettings extends NotificationSelection {
  enabled: boolean;
  server_url: string;
  topic: string;
  auth_mode: NtfyAuthMode;
  username: string | null;
  has_secret: boolean;
  config_version: number;
}

export function canReuseNotificationSecret(current: StoredNotificationSettings, input: NotificationSettingsInput) {
  return current.auth_mode === input.auth_mode && current.server_url === input.server_url
    && (input.auth_mode !== "password" || current.username === input.username)
    && Boolean(current.encrypted_secret && current.secret_iv);
}

export function selectMessagesForNotification(
  messages: readonly AuthoritativeMessage[],
  selection: NotificationSelection,
) {
  if (selection.selection_mode === "all") return [...messages];
  const selected = new Set(selection.selected_message_types);
  return messages.filter((message) =>
    selected.has(catalogKey(message.source_kind, message.message_type)));
}

export function notificationKey(
  configVersion: number,
  deviceId: string,
  message: AuthoritativeMessage,
) {
  return `${configVersion}:${deviceId}:${message.message_id}`;
}

export function toPublicNotificationSettings(
  settings: StoredNotificationSettings,
): PublicNotificationSettings {
  return {
    enabled: settings.enabled,
    server_url: settings.server_url,
    topic: settings.topic,
    auth_mode: settings.auth_mode,
    username: settings.username,
    has_secret: Boolean(settings.encrypted_secret),
    selection_mode: settings.selection_mode,
    selected_message_types: [...settings.selected_message_types],
    config_version: settings.config_version,
  };
}
