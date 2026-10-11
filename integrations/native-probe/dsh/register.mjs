import { createRequire } from "node:module";
import { mkdir, readFile, writeFile, rename, access, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const begin = "# SLK NATIVE PROBE BEGIN v1";
const end = "# SLK NATIVE PROBE END v1";
const block = `${begin}\n- insert:\n    - id: slk-native-probe\n      name: './plugins/slk-native-probe/activity.mjs'\n${end}\n`;
const digest = (value) => createHash("sha256").update(value).digest("hex");
async function existing(path) { try { return await readFile(path); } catch (error) { if (error.code === "ENOENT") return undefined; throw error; } }

export async function rollback(receiptPath) {
  const receipt = JSON.parse(await readFile(receiptPath, "utf8"));
  if (receipt.schema !== "slk.native-probe-registration/v1" || !Array.isArray(receipt.actions)) throw new Error("Invalid native probe receipt.");
  const home = resolve(receipt.home);
  const allowed = new Set([join(home, "cordis.patch.yml"), ...["activity.mjs", "probe.mjs", "slk-native-probe.exe"].map((name) => join(home, "plugins", "slk-native-probe", name))]);
  const restored = [], conflicts = [], pending = [];
  for (const action of [...receipt.actions].reverse()) {
    if (!allowed.has(resolve(action.path))) throw new Error("Receipt names an unmanaged path.");
    const current = await existing(action.path);
    if ((!current && !action.before_sha256) || (current && digest(current) === action.before_sha256)) continue;
    if (!current || digest(current) !== action.after_sha256) { conflicts.push(action.path); continue; }
    let prior;
    if (action.backup) {
      if (dirname(resolve(action.backup)) !== dirname(resolve(receiptPath))) throw new Error("Receipt backup is outside its transaction.");
      prior = await readFile(action.backup); if (digest(prior) !== action.before_sha256) throw new Error("Backup hash mismatch.");
    }
    pending.push({ ...action, prior });
  }
  // Keep the whole registration if a user changed any owned surface; removing
  // its still-referenced plugin would also break that user-edited native YAML.
  if (conflicts.length) return { restored, conflicts };
  for (const action of pending) {
    if (action.backup) {
      const temporary = `${action.path}.slk-rollback-${randomUUID()}`;
      try { await writeFile(temporary, action.prior, { flag: "wx" }); await rename(temporary, action.path); } finally { await rm(temporary, { force: true }); }
    } else await rm(action.path);
    restored.push(action.path);
  }
  return { restored, conflicts };
}

export function updatedPatch(original, parsed) {
  if (!Array.isArray(parsed)) throw new Error("Native patch is not a list; existing user file preserved.");
  const occurrences = original.split(begin).length - 1;
  const endings = original.split(end).length - 1;
  if (occurrences !== endings || occurrences > 1) throw new Error("Owned probe markers are ambiguous; existing user file preserved.");
  if (!occurrences) {
    if (parsed.some((entry) => entry?.insert?.some((row) => ["slk-native-probe", "slk-native-activity"].includes(row?.id)))) {
      throw new Error("Unmanaged legacy probe insert requires explicit migration; existing user file preserved.");
    }
    const base = parsed.length === 0 ? original.replace(/^([\t ]*)\[\]([\t ]*(?:#.*)?)$/m, "$1$2") : original;
    return `${base}${base.endsWith("\n") || !base ? "" : "\n"}${block}`;
  }
  const first = original.indexOf(begin);
  const last = original.indexOf(end, first) + end.length;
  return original.slice(0, first) + block.trimEnd() + original.slice(last);
}

// Installer/launcher calls this once per actual DSH home. Native parser only
// validates; user YAML/comments/!!js bytes are never reserialized.
export async function register(home, nativePackage, helper) {
  const require = createRequire(resolve(nativePackage, "package.json"));
  const bootPath = require.resolve("@deepseek-ai/dsh-app-boot");
  const { loadOptionalPatches, loadOverlayPatches } = await import(pathToFileURL(bootPath).href);
  await access(helper);
  const path = join(home, "cordis.patch.yml");
  const originalBytes = await existing(path);
  const original = originalBytes === undefined ? "" : originalBytes.toString("utf8");
  const parsed = original ? loadOptionalPatches("slk-native-probe", path) : [];
  const next = updatedPatch(original, parsed);
  await mkdir(home, { recursive: true });
  const temporary = join(home, `.slk-native-probe-${randomUUID()}.patch.yml`);
  await writeFile(temporary, next, { encoding: "utf8", flag: "wx" });
  const receipt = { schema: "slk.native-probe-registration/v1", home, load_state: "PENDING_RELOAD", actions: [] };
  const transaction = join(home, ".slk-native-probe-backups", randomUUID());
  const receiptPath = join(transaction, "receipt.json");
  const save = async (target, data) => {
    const old = await existing(target); if (old && old.equals(data)) return;
    await mkdir(transaction, { recursive: true });
    let backup;
    if (old) { backup = join(transaction, `${receipt.actions.length}.before`); await writeFile(backup, old, { flag: "wx" }); }
    const action = { path: target, before_sha256: old ? digest(old) : null, after_sha256: digest(data), ...(backup ? { backup } : {}) };
    receipt.actions.push(action); await writeFile(receiptPath, JSON.stringify(receipt, null, 2));
    const replacement = `${target}.slk-install-${randomUUID()}`;
    try { await writeFile(replacement, data, { flag: "wx" }); await rename(replacement, target); } finally { await rm(replacement, { force: true }); }
  };
  try {
    loadOverlayPatches("slk-native-probe", temporary);
    const plugin = join(home, "plugins", "slk-native-probe"); await mkdir(plugin, { recursive: true });
    const source = dirname(fileURLToPath(import.meta.url));
    for (const name of ["probe.mjs", "activity.mjs"]) await save(join(plugin, name), await readFile(join(source, name)));
    await save(join(plugin, "slk-native-probe.exe"), await readFile(helper));
    // Do not replace a user edit made while validating/copying the artifacts.
    const current = await existing(path);
    if ((current === undefined) !== (originalBytes === undefined) ||
        (current !== undefined && !current.equals(originalBytes))) throw new Error("DSH patch changed concurrently; new probe patch not applied.");
    if (next !== original) {
      await mkdir(transaction, { recursive: true });
      let backup; if (originalBytes !== undefined) { backup = join(transaction, "patch.before"); await writeFile(backup, originalBytes, { flag: "wx" }); }
      receipt.actions.push({ path, before_sha256: originalBytes !== undefined ? digest(originalBytes) : null, after_sha256: digest(Buffer.from(next)), ...(backup ? { backup } : {}) });
      await writeFile(receiptPath, JSON.stringify(receipt, null, 2));
      await rename(temporary, path);
    }
    return { changed: receipt.actions.length > 0, home, path, load_state: "PENDING_RELOAD", ...(receipt.actions.length ? { receipt: receiptPath } : {}) };
  } catch (error) {
    if (receipt.actions.length) {
      error.receipt = receiptPath;
      try {
        const recovery = await rollback(receiptPath);
        error.conflicts = recovery.conflicts;
        error.rollback_state = recovery.conflicts.length ? "ROLLBACK_FAILED" : "ROLLED_BACK";
      } catch (recoveryError) {
        error.rollback_state = "ROLLBACK_FAILED";
        error.rollback_error = recoveryError.code ?? recoveryError.name ?? "Error";
      }
    }
    throw error;
  } finally { await rm(temporary, { force: true }); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [home, nativePackage, helper] = process.argv.slice(2);
  try {
    if (home === "rollback" && nativePackage) console.log(JSON.stringify(await rollback(resolve(nativePackage))));
    else {
      if (!home || !nativePackage || !helper) throw new Error("Missing registration inputs.");
      let selectedHome = resolve(home);
      if (home === "--native-home") {
        const require = createRequire(resolve(nativePackage, "package.json"));
        const { resolveDshHome } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-home-paths")).href);
        selectedHome = resolveDshHome();
      }
      console.log(JSON.stringify(await register(selectedHome, resolve(nativePackage), resolve(helper))));
    }
  } catch (error) {
    // Machine-readable failure state, never native parser excerpts/user YAML.
    console.error(JSON.stringify({ error: "SLK_NATIVE_PROBE_REGISTRATION_FAILED", cause: error.code ?? error.name ?? "Error", rollback_state: error.rollback_state ?? (home === "rollback" ? "ROLLBACK_FAILED" : "UNCHANGED"), ...(error.receipt ? { receipt: error.receipt, conflicts: error.conflicts ?? [], ...(error.rollback_error ? { rollback_error: error.rollback_error } : {}) } : home === "rollback" && nativePackage ? { receipt: resolve(nativePackage) } : {}) }));
    process.exitCode = 1;
  }
}
