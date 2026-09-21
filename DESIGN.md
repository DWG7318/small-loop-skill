# LE BI Design System

## Direction

LE BI is a frameless, read-only desktop status strip inspired by 1990s engineering calculators. It is intentionally smaller than a dashboard: one compact window, one active SLK list, one archive view, and progressive disclosure inside each SLK row.

Design settings: low variance, almost no motion, high information density, muted color.

## Shell

- Fixed 940 px working width, minimum 720 px; height follows content up to a safe screen bound.
- No native frame, maximize, or resize. The custom top bar provides archive, always-on-top, minimize, and a red close control.
- The top bar is the drag surface. Controls use small beveled calculator buttons and visible keyboard focus.
- System Chinese sans is used for labels; Cascadia Mono/Consolas for IDs, versions, time, and measurements. No remote fonts.

## Active row

Every collapsed row is one SLK Run and shows, left to right:

1. start date;
2. origin: independent, `CLK · project`, or `GLK · project`;
3. project name, short Run name, and one-line description;
4. total recorded work duration;
5. eight-segment progress;
6. passed/total CELL count and current CELL work duration;
7. factual state or current responsibility;
8. SLK version;
9. disclosure chevron.

Rows from one CLK/GLK parent share a stable very light tint. The source text remains visible, so color is never the only grouping cue.

## Expanded SLK

Expansion stays inside the selected row and never opens a second pane. It contains:

- one three-column role strip for Supervisor, Checker, and Worker with Agent runtime, model, and reasoning level;
- ordered CELL rows with state mark, CELL number, title, medium-detail objective/result, active work time, and rework count when applicable.

LE BI does not render a timeline, inspector, project rail, SLK TOKEN payload, raw evidence, CLK Chain, GLK Node, Fusion, or DAG. Agents can query those facts when deeper diagnosis is needed.

## Archive

The archive button toggles an in-window archive section. `closed`, `abandoned`, and `superseded` SLKs enter it immediately and independently of any parent project. Archived rows keep the same expansion behavior and are visually subdued without losing text contrast.

## Status and time

Green means recorded completion, blue means an authored active phase, amber means waiting, and red means rework or attention. Exact text is always present. “Working” is shown only from an unfinished authored work/check event; token ownership alone never creates it.

Total and current CELL work time are unions of recorded active intervals. Candidate submission, inspection result, blocker, and resource-contention boundaries stop the relevant interval; waiting does not accumulate.

## States and motion

Loading, unconfigured, empty, unsupported-schema, and read-error states occupy the same compact shell. A transient failure keeps the last good snapshot and marks it stale. The only motion is the short disclosure-chevron rotation, disabled under reduced-motion preference.

## Integration boundary

The React view and Rust read core remain standalone and do not import LCaS. A future LCaS rc.08/rc.09 panel may host the same read components without changing the SQLite authority or allowing BI writes.
