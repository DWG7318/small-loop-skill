import assert from "node:assert/strict";
import { test } from "node:test";
import { updatedPatch } from "./register.mjs";
test("owned append is idempotent and preserves user text and expressions", () => {
  const old = "# owner comment\n- id: existing\n  config: !!js 'ctx.value'\n";
  const once = updatedPatch(old, [{ id: "existing" }]);
  assert.ok(once.startsWith(old)); assert.equal(updatedPatch(once, []), once);
});
test("ambiguous and unmanaged probe entries fail without rewriting YAML", () => {
  assert.throws(() => updatedPatch("# SLK NATIVE PROBE BEGIN v1", []));
  assert.throws(() => updatedPatch("- insert: []\n", [{ insert: [{ id: "slk-native-activity" }] }]));
  assert.throws(() => updatedPatch("value", {}));
});
