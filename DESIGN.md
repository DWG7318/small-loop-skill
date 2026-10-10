# LE BI Design System

## Direction

LE BI is a frameless, read-only desktop status strip inspired by 1990s engineering calculators. It is intentionally smaller than a dashboard: one compact window, one active SLK list, one archive view, and progressive disclosure inside each SLK row.

Design settings: low variance, almost no motion, high information density, muted color.

## Shell

- Initial 940 px width, minimum 720 px; automatic height changes preserve the current width and retain the SLK version at the minimum width.
- Height follows the complete content border box with a 94 px minimum, capped by the current monitor's work area below the window's current position and converted using its display scale. Collapse targets the intrinsic height directly. Only when less than the native minimum remains below the window is it moved upward by the minimum necessary distance, preserving its horizontal position.
- No native frame, maximize, or resize. The custom top bar provides archive, always-on-top, minimize, and a red close control.
- The top bar is the drag surface. Controls use small beveled calculator buttons and visible keyboard focus.
- System Chinese sans is used for labels; Cascadia Mono/Consolas for IDs, versions, time, and measurements. No remote fonts.

## Active row

Every collapsed row is one SLK Run and shows, left to right:

1. start date;
2. origin: independent, `CLK · project`, or `GLK · project`;
3. project name, short Run name, and one-line description;
4. total recorded work duration;
5. proportional segmented progress in eight columns within a 62 px footprint: 8 segments for 0–8 effective CELLs, 16 for 9–16, and 24 for 17 or more; incomplete work never fills every segment;
6. passed/total CELL count and current CELL work duration;
7. factual state or current responsibility;
8. SLK version;
9. unread green dot when applicable and disclosure chevron.

Rows from one independent project or CLK/GLK parent share a stable very light tint. Independent-project tinting uses immutable project identity, while the source text remains visible so color is never the only grouping cue.

## Expanded SLK

Expansion stays inside the selected row and never opens a second pane. Exactly one Run may be expanded across active and archived records; selecting it again collapses it. Opening acknowledges its displayed authoritative messages; collapsing does not. It contains:

- one role strip for Supervisor, Checker, Worker, and the registered Overwatcher, with Agent runtime, model, and reasoning level; four registered roles use four columns;
- a separate Overwatcher assurance strip showing recorded binding, native liveness, and cycle facts;
- CELL rows with state mark, original CELL number, title, medium-detail objective/result, active work time, and rework count when applicable. Display reverses a copy of the existing GO-then-CELL execution list, so the latest record is first without changing the plan, execution order, current-CELL fallback, or timing data.

There are only two scrolling levels. Active and archived Run headers share one outer main scroller whose natural budget is five headers; an expanded detail body adds height without consuming a header slot. CELL records alone form the inner scroller with at most six measured rows, visible scrollbar, keyboard focus, and contained overscroll. Role and Overwatcher strips stay outside it. Work-area constraints may reduce visible rows; all records remain reachable and no list is sliced.

LE BI does not render a timeline, inspector, project rail, SLK TOKEN payload, raw evidence, CLK Chain, GLK Node, Fusion, or DAG. Agents can query those facts when deeper diagnosis is needed.

## Archive

The archive button toggles an in-window archive section. `closed`, `abandoned`, and `superseded` SLKs enter it immediately and independently of any parent project. Archived rows keep the same expansion behavior and are visually subdued on an opaque background without losing text contrast. Hiding the archive or removing the expanded Run from the visible source clears its disclosure and detail-height budget.

## Status and time

Green means recorded completion, blue means an authored active phase, amber means waiting, and red means rework or attention. Exact text is always present. “Working” is shown only from an unfinished authored work/check event; token ownership alone never creates it.

Formal pause-request, paused, and resumed lifecycle events remain visible despite later administrative role registration. `D2_PASSED` means acceptance passed awaiting close, not a closed Run. `D1_FAILED` means awaiting Supervisor guidance; only `REWORK_REQUESTED` claims rework. Overwatcher anomalies or overdue cadence mean attention is needed, not that the observer paused.

Total and current CELL work time are unions of recorded active intervals. Candidate submission, inspection result, blocker, and resource-contention boundaries stop the relevant interval; waiting does not accumulate.

## States and motion

Loading, unconfigured, empty, unsupported-schema, and read-error states occupy the same compact shell. A transient failure keeps the last good snapshot and marks it stale. The only motion is the short disclosure-chevron rotation, disabled under reduced-motion preference.

## Integration boundary

The React view and Rust read core remain standalone and do not import LCaS. A future LCaS rc.08/rc.09 panel may host the same read components without changing the SQLite authority or allowing BI writes.
