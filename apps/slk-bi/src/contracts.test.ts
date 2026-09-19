import { describe, expect, it } from "vitest";

import { parseRunProjection } from "./contracts";
import { runFixture } from "./test/fixtures";

describe("SLK BI contracts", () => {
  it("accepts the exact v1 Run projection", () => {
    expect(parseRunProjection(runFixture).schema_version).toBe("slk.bi.run/v1");
  });

  it("rejects future schemas before reading domain fields", () => {
    expect(() =>
      parseRunProjection({ ...runFixture, schema_version: "slk.bi.run/v2" }),
    ).toThrow("SLK_BI_SCHEMA_UNSUPPORTED");
  });

  it("rejects malformed projection collections", () => {
    expect(() => parseRunProjection({ ...runFixture, roles: {} })).toThrow(
      "SLK_BI_PROJECTION_INVALID",
    );
  });
});
