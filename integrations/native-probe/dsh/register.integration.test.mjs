import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdir, mkdtemp, readFile, writeFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { register, rollback } from "./register.mjs";

const native = process.env.SLK_DSH_NATIVE_PACKAGE_ROOT;
const helper = join(dirname(fileURLToPath(import.meta.url)), "../artifacts/windows-amd64/slk-native-probe.exe");
test("real native parser: owner YAML/expression retained, registration idempotent, exact rollback", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-"));
  const path = join(home, "cordis.patch.yml");
  const original = "# owner bytes\n- id: fixture\n  config: !!js process.env.FIXTURE\n";
  await writeFile(path, original);
  const first = await register(home, native, helper);
  assert.equal(first.changed, true); assert.equal(first.load_state, "PENDING_RELOAD");
  assert.ok((await readFile(path, "utf8")).startsWith(original));
  const second = await register(home, native, helper); assert.equal(second.changed, false);
  assert.deepEqual((await rollback(first.receipt)).conflicts, []);
  assert.equal(await readFile(path, "utf8"), original);
  assert.deepEqual(await rollback(first.receipt), { restored: [], conflicts: [] });
});
test("real native empty-list patch works, user concurrent edit blocks whole rollback", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-"));
  const path = join(home, "cordis.patch.yml"); await writeFile(path, "# owner\n[]\n");
  const first = await register(home, native, helper);
  const changed = (await readFile(path, "utf8")) + "# owner changed after install\n"; await writeFile(path, changed);
  const result = await rollback(first.receipt); assert.deepEqual(result.conflicts, [path]); assert.deepEqual(result.restored, []);
  assert.equal(await readFile(path, "utf8"), changed); await access(join(home, "plugins/slk-native-probe/activity.mjs"));
});
test("existing zero-byte owner patch is backed up and restored, never deleted", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-empty-"));
  const path = join(home, "cordis.patch.yml");
  await writeFile(path, Buffer.alloc(0));
  const first = await register(home, native, helper);
  const receipt = JSON.parse(await readFile(first.receipt, "utf8"));
  const action = receipt.actions.find((entry) => entry.path === path);
  assert.equal(action.before_sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.deepEqual(await readFile(action.backup), Buffer.alloc(0));
  assert.deepEqual((await rollback(first.receipt)).conflicts, []);
  assert.deepEqual(await readFile(path), Buffer.alloc(0));
  assert.deepEqual(await rollback(first.receipt), { restored: [], conflicts: [] });
});
test("corrupt receipt backup is rejected before restoring any managed file", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-"));
  const plugin = join(home, "plugins/slk-native-probe"); await mkdir(plugin, { recursive: true });
  await writeFile(join(home, "cordis.patch.yml"), "# owner\n[]\n");
  await writeFile(join(plugin, "activity.mjs"), "// prior plugin\n");
  const first = await register(home, native, helper);
  const receipt = JSON.parse(await readFile(first.receipt, "utf8"));
  const prior = new Map(await Promise.all(receipt.actions.map(async (action) => [action.path, await readFile(action.path)])));
  const backup = receipt.actions.find((action) => action.path.endsWith("activity.mjs")).backup;
  await writeFile(backup, "corrupted backup");
  await assert.rejects(rollback(first.receipt), /Backup hash mismatch/);
  for (const action of receipt.actions) assert.deepEqual(await readFile(action.path), prior.get(action.path));
});
test("partial registration failure exposes its receipt and verified rollback result", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-"));
  const path = join(home, "cordis.patch.yml"); const original = "# owner\n[]\n";
  await writeFile(path, original);
  await assert.rejects(register(home, native, home), (error) => {
    assert.equal(error.rollback_state, "ROLLED_BACK");
    assert.equal(typeof error.receipt, "string"); assert.deepEqual(error.conflicts, []); return true;
  });
  assert.equal(await readFile(path, "utf8"), original);
  await assert.rejects(access(join(home, "plugins/slk-native-probe/activity.mjs")), { code: "ENOENT" });
});
test("CLI prevalidation failure explicitly reports unchanged and emits no user configuration", { skip: !native }, async () => {
  const home = await mkdtemp(join(tmpdir(), "slk-native-register-"));
  const command = spawnSync(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), "register.mjs"), home, native, join(home, "missing.exe")], { windowsHide: true, encoding: "utf8" });
  assert.equal(command.status, 1); assert.equal(command.stdout, "");
  assert.deepEqual(JSON.parse(command.stderr), { error: "SLK_NATIVE_PROBE_REGISTRATION_FAILED", cause: "ENOENT", rollback_state: "UNCHANGED" });
  await assert.rejects(access(join(home, "cordis.patch.yml")), { code: "ENOENT" });
});

test("CLI native-home mode uses the actual native resolver for relative, tilde and blank overrides", { skip: !native }, async (t) => {
  for (const [name, override] of [["relative", "relative 中文 %LITERAL% ^home"], ["tilde", "~/tilde 中文 %LITERAL% ^home"], ["blank", " \t "]]) {
    await t.test(name, async () => {
      const work = await mkdtemp(join(tmpdir(), "slk-native-home-"));
      const profile = join(work, "profile 中文 %LITERAL% ^home");
      const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !["userprofile", "dsh_home", "appdata", "localappdata"].includes(key.toLowerCase())));
      Object.assign(env, { USERPROFILE: profile, HOME: profile, APPDATA: join(profile, "AppData/Roaming"), LOCALAPPDATA: join(profile, "AppData/Local"), DSH_HOME: override });
      // Expected identity comes from the real product API in its own isolated
      // environment, not a second implementation of tilde/profile semantics.
      const nativeResolution = spawnSync(process.execPath, ["--input-type=module", "-e",
        "import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';const r=createRequire(process.argv[1]);const {resolveDshHome}=await import(pathToFileURL(r.resolve('@deepseek-ai/dsh-home-paths')).href);console.log(resolveDshHome());", resolve(native, "package.json")], { windowsHide: true, encoding: "utf8", env, cwd: work });
      assert.equal(nativeResolution.status, 0, nativeResolution.stderr);
      const expectedHome = nativeResolution.stdout.trim();
      assert.ok(expectedHome.startsWith(work));
      const command = spawnSync(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), "register.mjs"), "--native-home", native, helper], { windowsHide: true, encoding: "utf8", env, cwd: work });
      assert.equal(command.status, 0, command.stderr);
      const result = JSON.parse(command.stdout);
      assert.equal(result.home, expectedHome);
      assert.equal(result.load_state, "PENDING_RELOAD");
      await access(join(expectedHome, "cordis.patch.yml"));
      const recovery = await rollback(result.receipt);
      assert.deepEqual(recovery.conflicts, []);
      await assert.rejects(access(join(expectedHome, "cordis.patch.yml")), { code: "ENOENT" });
    });
  }
});
