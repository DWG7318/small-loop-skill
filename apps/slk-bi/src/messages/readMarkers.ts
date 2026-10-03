export interface ReadMarker {
  known_message_ids: string[];
  read_message_ids: string[];
}

function unique(values: readonly string[]) {
  return [...new Set(values.filter(Boolean))].sort();
}

export function bootstrapReadMarker(messageIds: readonly string[]): ReadMarker {
  const ids = unique(messageIds);
  return { known_message_ids: ids, read_message_ids: ids };
}

export function mergeReadMarker(
  marker: ReadMarker,
  displayedMessageIds: readonly string[],
): ReadMarker {
  return {
    known_message_ids: unique([...marker.known_message_ids, ...displayedMessageIds]),
    read_message_ids: unique(marker.read_message_ids),
  };
}

export function acknowledgeDisplayedMessages(
  marker: ReadMarker,
  displayedMessageIds: readonly string[],
): ReadMarker {
  return {
    known_message_ids: unique([...marker.known_message_ids, ...displayedMessageIds]),
    read_message_ids: unique([...marker.read_message_ids, ...displayedMessageIds]),
  };
}

export function hasUnreadMessages(
  marker: ReadMarker,
  displayedMessageIds: readonly string[],
) {
  const read = new Set(marker.read_message_ids);
  return unique(displayedMessageIds).some((messageId) => !read.has(messageId));
}

export function parseReadMarker(value: string | null): ReadMarker | undefined {
  if (!value) return undefined;
  try {
    const parsed = JSON.parse(value) as Partial<ReadMarker>;
    if (!Array.isArray(parsed.known_message_ids) || !Array.isArray(parsed.read_message_ids)) {
      return undefined;
    }
    if (
      parsed.known_message_ids.some((value) => typeof value !== "string")
      || parsed.read_message_ids.some((value) => typeof value !== "string")
    ) return undefined;
    return {
      known_message_ids: unique(parsed.known_message_ids),
      read_message_ids: unique(parsed.read_message_ids),
    };
  } catch {
    return undefined;
  }
}
