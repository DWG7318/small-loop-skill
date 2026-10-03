import { describe, expect, it } from "vitest";

import {
  acknowledgeDisplayedMessages,
  bootstrapReadMarker,
  hasUnreadMessages,
  mergeReadMarker,
} from "./readMarkers";

describe("BI 1.1 read markers", () => {
  it("treats the historical bootstrap as read", () => {
    const marker = bootstrapReadMarker(["EVENT:a", "EVENT:b"]);
    expect(hasUnreadMessages(marker, ["EVENT:a", "EVENT:b"])).toBe(false);
  });

  it("shows a dot only for a new authoritative message id", () => {
    const marker = bootstrapReadMarker(["EVENT:a"]);
    expect(hasUnreadMessages(marker, ["EVENT:a"])).toBe(false);
    expect(hasUnreadMessages(marker, ["EVENT:a", "EVENT:b"])).toBe(true);
  });

  it("acknowledges only the displayed set and a stale snapshot cannot regress it", () => {
    const opened = acknowledgeDisplayedMessages(
      bootstrapReadMarker(["EVENT:a"]),
      ["EVENT:a", "EVENT:b"],
    );
    const afterStale = mergeReadMarker(opened, ["EVENT:a"]);

    expect(hasUnreadMessages(afterStale, ["EVENT:a", "EVENT:b"])).toBe(false);
    expect(hasUnreadMessages(afterStale, ["EVENT:a", "EVENT:b", "EVENT:c"])).toBe(true);
  });

  it("does not create another update for duplicate ids", () => {
    const marker = acknowledgeDisplayedMessages(
      bootstrapReadMarker([]),
      ["EVENT:a"],
    );
    expect(hasUnreadMessages(marker, ["EVENT:a", "EVENT:a"])).toBe(false);
  });
});
