# SLK native probe 1.0.0

Native metadata evidence only. No Run selector, agent, daemon, scheduler,
engineering decision, BI write, TOKEN write, automatic repair or transcript copy.
The original document/log reading tools remain uncapped.

## Deployment inputs

Developer builds with `./build.ps1 -Go <go executable>` (Go 1.25.5+ and Git).
The same source module builds the short-lived `slk-native-probe.exe` helper and
the clearly modified OCRV `1.12.13-slkprobe.1.0.0` executable. The official OCRV
source archive, exact two-file lifecycle/writer patch and all original license
notices are in `upstream`; this is not an unchanged upstream release.

DSH 0.2.0-rc.2 native home registration:

```text
node dsh/register.mjs <actual DSH_HOME> <DSH root containing node_modules> <slk-native-probe.exe>
node dsh/register.mjs rollback <returned receipt path>
```

The original native parser validates YAML, including `!!js`, without rewriting
owner entries/comments. Only the marked insert and three managed files under
`<home>/plugins/slk-native-probe/` change. Identical files are not recopied. A
receipt contains local exact backups/hashes, not printed user config or keys.
Rollback first checks every current hash; owner edits cause conflicts and keep
the whole registration. Receipt success is **PENDING_RELOAD**, not evidence
that an already-running host loaded it. All ordinary native calls using that
home load the original native home patch, not only SLK wrapper calls. Other
homes or embeddings bypassing native CLI boot require their own integration.
CLI failure exits 1 with a single metadata-only JSON stderr object. If a
transaction began, it includes `receipt`, `rollback_state` (ROLLED_BACK or
ROLLBACK_FAILED), `conflicts`, and a rollback error code when needed. A failure
before any managed write explicitly reports UNCHANGED. The outer
installer must not claim successful rollback on conflict or unknown state.

## Sampling and evidence

One 60-second sampler per actual DSH host. Native `sessionQuery.listSessions()`
includes persisted and live objects; one object's activity never stands in for
another. Archive identities come from the actual workspace registry, or the
actual routed JSON workspace medium when the official headless profile omits
the Web registry. Missing native JSON workspace means no archive marker;
malformed/inaccessible/unsupported media means UNKNOWN. No BI-derived archive.
Only metadata comes from native events; the event hash is the canonical emitted
event, explicitly `DSH_NATIVE_EMISSION`, not a claimed durable record hash.

OCRV's original CLI `run()` starts/stops its in-process sampler. Only a native
writer that successfully opened its exact file registers Session ownership.
All native repository session directories are listed. Complete JSONL records
are consumed incrementally using physical file identity/offset; first scans or
changed sources read full original records without a line-size limit. Compact
cursors can be reused from the existing snapshot, with no extra disk index.
Buffered/partial-tail events are not durable records. No verified native OCRV
archive marker exists in this pinned source, so all its sessions are included.
An existing nonterminal file alone is UNKNOWN, not RUNNING. `owner_bound` only
means the native writer in that process opened that source, not model activity.
Shared cursor reuse never inherits another process's writer ownership. A native
`session_end` alone means CLOSED, not success; a recognized original manifest's
terminal state distinguishes COMPLETED, FAILED, PARTIAL and SKIPPED. None is a
SLK D1 judgment.

Device/host/PID plus OS creation identity, native source path/physical identity,
size/mtime, exact sample time, last event metadata/hash are retained. Exit does
not fabricate task completion: DSH keeps the last actual sample time and records
EXITING separately because dependencies may already be disposed. OCRV can still
read its native files at its original defer hook and final-samples them. Query
checks present OS process identity separately and never renews sample time.

## Storage and read-only query

```text
slk-native-probe.exe --tool dsh query
slk-native-probe.exe --tool ocrv --session <exact native Session ID> query
```

Default storage is `%LOCALAPPDATA%/SLK/native-probe/<tool>` on Windows and
`~/.local/state/slk/native-probe/<tool>` otherwise. Each tool's **combined**
host snapshot is at most 5MiB, so old snapshot plus the one replacement file
remain within 10MiB. Cross-process OS mutex/flock serializes merge/replacement;
Windows mutex acquisition/release stays on the same OS thread. Crash leftovers
at the one owned temporary filename are removed under that same lock. Failed
writes preserve the previous readable snapshot. Capacity omissions retain
counts and force UNKNOWN; exhausted host-index capacity returns an explicit
write error rather than inventing complete coverage. Original logs are never
deleted, truncated or copied into the budget. No dialogue/reasoning/tool args or
results are persisted here. OW requests one exact Session summary, not the full
10MiB. Windows is natively tested; Linux syscall support is source/build tested
only until separately exercised on Linux.

## Tests

`go test ./...` exercises distinct stopped/running sessions, shared budget,
partial/corrupt native records, >10MiB original records, physical replacement,
read-only query, write failure, four real writer processes and crashed mutex/
temporary-file recovery. `node --test dsh/*.test.mjs` checks native corpus/archive
and cadence plus native parser registration/rollback when
`SLK_DSH_NATIVE_PACKAGE_ROOT` names a prepared official DSH package root.
Product installation does not run these development tests or compile tools.
