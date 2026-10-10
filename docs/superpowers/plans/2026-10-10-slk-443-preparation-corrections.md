# SLK 4.4.4 Preparation Corrections Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; Supervisor independently checks this package before deployment or any preparation-sample rerun.

**Goal:** Remove the audited preparation blockers without changing engineering acceptance, live Run state or installed runtime.

**Architecture:** Correct existing equality/diagnostic/readiness contracts; reuse the existing DSH workspace result drop and trusted host preservation. No new service, role, wrapper, migration or general recovery path.

**Tech Stack:** Existing Rust state core, Python transport, JSON Schema and Windows runtime guide.

## Verified input and boundaries

- Baseline `fec83184403cbf6b4d8a896dd1c91d130b702f59`; preparation ledger SHA256 `ab66b5cb6bfd0ba45a6d14809f615ad3d98088104b6311b46a54bd1fde393400`; index SHA256 `02888d3282fe6c50aaa4a12d0e7a68145e12901709b8c31bcb2045a7c6ec5c20`. All54 evidence/17 source hashes match.
- Owner's original Supervisor message says continue preparation; the delegated scope is this correction package, not product dispatch. Product and sample TOKEN/SQLite, original OW, credentials, history and shared Temporal are untouched.
- PA001/002/007 are Supervisor sequence corrections; PA003/general migration and codebase-wide slimming are outside this package. Do not claim sample READY from unit tests.
- Supervisor approved patch4.4.4 / BI1.1.1. Existing4.4.3 Run/startup/OW/history remain4.4.3; no new migration or live rebind. Version producer/consumer changes are mechanical compatibility, not slimming.

## 1. Regression RED — complete

- [x] Same Session / independent Run evidence in bind and replacement; mismatched host still rejects. Python RED6 failed/93 passed; Rust RED3 failed/49 passed before production edits.
- [x] Native Rust `code` diagnostics, missing-OW schema, absent/null capacity and BI1.1.1 compatibility regressions; unsafe details remain hidden and failure creates no success receipt.
- [x] Patch-version RED4 Python failures and fresh Rust current-version failure establish actual4.4.4 production pairing, not a package relabel.

## 2. Minimal corrections — complete

- [x] `write.rs`: remove only per-Run evidence-reference equality from both shared-Session checks; retain identity/turn/cadence and individual evidence checks.
- [x] `supervisor_admin.py`: native `code` fallback through existing safe filtering. Cadence schema accepts existing `OVERWATCHER_MISSING` without suppressing it.
- [x] Readiness accepts absent/null context facts as UNKNOWN advisory, rejects invalid numbers, requires BI1.1.1 for actual4.4.3/4.4.4 method evidence, keeps old4.4.2 receipts readable.
- [x] Extend existing producers/compatibility sets to4.4.4; retain old workflow patch markers and4.4.3 D2/close/OW scope/window safeguards. The three scope/window regression cases run both4.4.3 and4.4.4.

## 3. PA004 / release guidance — complete (native rerun deferred)

- [x] Preparation uses existing authorized native requests and workspace originals, then trusted host byte-exact preservation/hash/standard Eval validation; it does not borrow Checker authority or count as a communication leg. Formal tasks retain descriptor `result_path`. No Git-external direct writes, vanished TEMP or stdout reconstruction.
- [x] Runtime guide current4.4.4/17Skills/BI1.1.1/OCRV1.12.13; existing preparation order and normal seven-leg communication clarified in place.
- [x] Existing DSH subprocess preservation/cleanup tests passed; no native DSH model permission/readback acceptance claimed. Supervisor reruns native preparation only after independent review/deployment.

## 4. Verification and handoff — active

- [x] Targeted Python199 passed/62.00s; Rust workspace156 passed/0 failed; final scope/window OW rerun52 passed/5.29s; cargo fmt check passed. Logs: `.codex/.tmp/preparation-444/`.
- [ ] Full Python, final manifest/repository checks, standard five-artifact release build and isolated package/install verification. No real installation or product-state commands.
- [ ] Record exact changed files, line-count split, tests, artifact hashes and unverified native gaps here; do not use old4.4.3 acceptance as evidence for this patch.
- [ ] Send completed package/evidence to exact Supervisor `01a0bed1-af60-7ac0-8003-d3d6f9d30124` for independent inspection. No self-deployment, new OW or sample READY claim.
