# BI/WebBI 1.1.4 — method-independent reading

BI is an independently versioned, precompiled tool. A method version is a label, not admission permission. This release reads the existing SLK state database (without migration/writes), and registered SLK Markdown Run records used by 3.x. An unknown source format is reported, not guessed. Arbitrary undocumented future formats are not claimed as supported.

## Existing Markdown

Run the precompiled executable directly; no runtime compilation, additional agent, or uploader:

```powershell
slk-bi.ps1 --bi-preview "D:/project/SLK-RUN-example.md" --project-id "project-id" --project-name "Project"
slk-bi.ps1 --bi-register "D:/project/SLK-RUN-example.md" --project-id "project-id" --project-name "Project"
slk-bi-desktop.exe
```

Preview only reads. Registration is performed by the **creating Supervisor's native session**, matching `Run 定义 / 创建Supervisor` in the record. For an older record, that Supervisor adds its exact original identity from the creation record, not from a title/current-role guess. Registration binds the canonical path, Run ID, project ID and original creator without silently replacing them. `--bi-read <run-id>` and `--bi-list` show the projection actually available to the GUI. `--config <path>` isolates diagnostics from production; it does not change method configuration.

BI reads the unique current summary, not the last keyword anywhere in history. Preserve `# SLK Run — <RUN-ID>`, `## Run 定义`, `## 当前摘要`, `## 成员`, `## GO 与 CELL 计划`. Method version, goal, start time and source identities stay original. Member columns can include `Agent`, `模型`, `推理`, `平台`; missing values are visibly unprovided. A plan can use a `CELL | 目标 | 状态 | 次数` table with explicit planned/working/d1_passed/d1_failed/split/exempt/unknown states. No second plan is needed. Existing numbered plan bullets and a current explicit complete D1 PASS list remain readable. Unknown individual outcomes are never inferred from an aggregate count or old FAIL history. Native CELL IDs, including split suffixes, are preserved.

Free-text current status is visibly labeled `记录：…`, not certified as live execution. Missing timings show `—`, not invented zero-minute work. Source changes generate view-only unread markers, not fabricated Agent event types or ntfy notifications. Formal notification types remain Agent-authored.

## Archive authority

```powershell
slk-bi.ps1 --bi-archive "RUN-ID"
```

The source must already explicitly declare `CLOSED` or `ABANDONED`, and the native caller must match the immutable registered creator. Other Supervisors, Worker/Checker/OW, missing/contradictory caller identities and public WebBI viewers cannot use this entry to archive. No public archive mutation endpoint or desktop archive-action button is added. The existing archive button only changes visibility.

The command saves a BI archive receipt/snapshot, **never writes the engineering record or grants D2 PASS/RUN_CLOSED**. A closed registered Markdown Run remains visible as `已完成 · 待归档` until this receipt exists. Archival preserves original creator, source revision and history; repeated archival is idempotent. A source disappearing after archival does not erase its saved snapshot. Session/owner changes require an explicit Owner-directed migration and preservation of original creation facts, not automatic reassignment.

Local identity presently uses host-provided `CODEX_THREAD_ID`/`CODEX_SESSION_ID`. There is no caller-supplied Supervisor option. This is cooperative-agent identity enforcement, not an OS security boundary against another process with the same filesystem account; do not spoof host variables. Other native identity adapters are not silently emulated. Existing state-database Runs retain their method's original authorized close/archive entrance. This BI change does **not** repair the deferred 4.5.4 Run09 close-census issue or bypass it.

## Storage and WebBI

BI source registrations/receipts live beside the existing configuration under `%LOCALAPPDATA%/SLK/bi-sources`. They are BI metadata, not a second engineering database. Individual source errors are reported without hiding other readable Runs. Duplicate Run IDs across local adapters are reported rather than silently merged.

The desktop's existing authenticated upload sends only its normalized projection. WebBI never reads local workbooks, Agent sessions, or project databases directly. Device ID + Run ID remains the storage key. Archived snapshots cannot be resurrected by an older upload or a newer envelope retrying stale active data. BI/WebBI are both 1.1.4; previous 1.1.0–1.1.3 uploads remain readable.
