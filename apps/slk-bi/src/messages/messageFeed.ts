import type { RunView } from "../contracts";

import { catalogEntry } from "./catalog";

export type SlkRole = "supervisor" | "checker" | "worker" | "overwatcher";
export type MessageSourceKind = "EVENT" | "OW_OBSERVATION";

export interface MessageCatalogEntry {
  source_kind: MessageSourceKind;
  message_type: string;
  label_zh: string;
  allowed_roles: SlkRole[];
  notification_eligible: boolean;
}

export interface AuthoritativeMessage {
  message_id: string;
  run_id: string;
  source_kind: MessageSourceKind;
  source_id: string;
  message_type: string;
  label_zh: string;
  author_role: SlkRole;
  author_identity_ref: string;
  go_id: string | null;
  cell_id: string | null;
  attempt: number | null;
  occurred_at: string;
}

function roleFor(run: RunView, roleInstanceId: string): SlkRole {
  const role = run.roles.find((item) => item.role_instance_id === roleInstanceId)?.role;
  if (!role) throw new Error("SLK_BI_MESSAGE_AUTHOR_INVALID");
  return role;
}

function validated(
  catalog: readonly MessageCatalogEntry[],
  message: Omit<AuthoritativeMessage, "label_zh">,
): AuthoritativeMessage {
  const entry = catalogEntry(catalog, message.source_kind, message.message_type);
  if (!entry) throw new Error("SLK_BI_MESSAGE_TYPE_INVALID");
  if (!entry.allowed_roles.includes(message.author_role)) {
    throw new Error("SLK_BI_MESSAGE_ROLE_INVALID");
  }
  if (!message.source_id || !message.author_identity_ref || !message.run_id) {
    throw new Error("SLK_BI_MESSAGE_IDENTITY_INVALID");
  }
  return { ...message, label_zh: entry.label_zh };
}

export function projectAuthoritativeMessages(
  run: RunView,
  catalog: readonly MessageCatalogEntry[],
): AuthoritativeMessage[] {
  const messages = [
    ...run.events.map((event) =>
      validated(catalog, {
        message_id: `EVENT:${event.event_id}`,
        run_id: run.run_id,
        source_kind: "EVENT" as const,
        source_id: event.event_id,
        message_type: event.event_type,
        author_role: roleFor(run, event.author_role_instance_id),
        author_identity_ref: event.author_role_instance_id,
        go_id: event.go_id,
        cell_id: event.cell_id,
        attempt: event.attempt,
        occurred_at: event.occurred_at,
      }),
    ),
    ...run.operational_observations.map((observation) =>
      validated(catalog, {
        message_id: `OW_OBSERVATION:${observation.observation_id}`,
        run_id: run.run_id,
        source_kind: "OW_OBSERVATION" as const,
        source_id: observation.observation_id,
        message_type: observation.kind,
        author_role: "overwatcher",
        author_identity_ref: observation.overwatcher_role_instance_id,
        go_id: observation.go_id,
        cell_id: observation.cell_id,
        attempt: observation.attempt,
        occurred_at: observation.occurred_at,
      }),
    ),
  ];
  const ids = new Set<string>();
  for (const message of messages) {
    if (ids.has(message.message_id)) throw new Error("SLK_BI_MESSAGE_ID_DUPLICATE");
    ids.add(message.message_id);
  }
  return messages.sort(
    (left, right) =>
      left.occurred_at.localeCompare(right.occurred_at)
      || left.message_id.localeCompare(right.message_id),
  );
}

export function projectSupportedAuthoritativeMessages(
  run: RunView,
  catalog: readonly MessageCatalogEntry[],
): AuthoritativeMessage[] {
  const knownLegacyAuthorityMismatch = (event: RunView["events"][number]) =>
    run.summary.slk_version === "4.0.0"
    && event.event_type === "REWORK_REQUESTED"
    && run.roles.find(({ role_instance_id }) =>
      role_instance_id === event.author_role_instance_id)?.role === "checker";

  return projectAuthoritativeMessages({
    ...run,
    events: run.events.filter((event) => !knownLegacyAuthorityMismatch(event)),
  }, catalog);
}
