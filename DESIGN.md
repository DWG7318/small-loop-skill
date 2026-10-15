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
5. segmented progress in ten equal-width columns with a consistent gap within a 62 px footprint: 0–30 effective CELLs use exactly that many segments, with no placeholders and a naturally shorter final row; totals above 30 use 30 proportional segments across three rows, never all filled before true completion. Exact counts remain in text and accessible progress values; this drawing cap never limits the plan or CELL records;
6. passed/total CELL count and current CELL work duration;
7. factual state or current responsibility;
8. SLK version;
9. unread green dot when applicable and disclosure chevron.

Rows from one independent project or CLK/GLK parent share a stable very light tint. Independent-project tinting uses immutable project identity, while the source text remains visible so color is never the only grouping cue.

## Expanded SLK

Expansion stays inside the selected row and never opens a second pane. Exactly one Run may be expanded across active and archived records; selecting it again collapses it. Opening acknowledges its displayed authoritative messages; collapsing does not. It contains:

- one role strip for Supervisor, Checker, Worker, and the registered Overwatcher, with Agent runtime, model, and reasoning level; four registered roles use four columns;
- a separate Overwatcher assurance strip showing recorded binding, native liveness, and cycle facts;
- CELL rows with state mark, original CELL number, title, medium-detail objective/result, active work time, and rework count when applicable. The shared desktop/WebBI presentation excludes untouched planned rows and sorts by newest recorded activity, then reverse execution order. It preserves source records, the full progress denominator, current-CELL fallback and timing data.

There are only two scrolling levels. Active and archived Run headers share one outer main scroller whose natural budget is five headers; an expanded detail body adds height without consuming a header slot. CELL records alone form the inner scroller with at most six measured rows, visible scrollbar, keyboard focus, and contained overscroll. Role and Overwatcher strips stay outside it. Work-area constraints may reduce visible rows; all records remain reachable and no list is sliced.

LE BI does not render a timeline, inspector, project rail, SLK TOKEN payload, raw evidence, CLK Chain, GLK Node, Fusion, or DAG. Agents can query those facts when deeper diagnosis is needed.

## Archive

The archive button toggles an in-window archive section. `closed`, `abandoned`, and `superseded` SLKs enter it immediately and independently of any parent project. Archived rows keep the same expansion behavior and the user's selected background alpha, never a parent-opacity fade of their text. Hiding the archive or removing the expanded Run from the visible source clears its disclosure and detail-height budget.

Background transparency uses a standard range input from 0% to 100% in 1% steps, with the current percentage shown, default 20%, saved under the existing local view preference key. Explicit 0% and prior 20%/40%/60%/80% choices restore; missing, blank or invalid values fall back to 20%, and unavailable storage never blocks the control. It affects frame/background colors only; do not use window or parent-element opacity. Text, icons and controls remain opaque and interactive even at 100%. Startup/render-failure fallback stays opaque. Desktop and WebBI share the slider; the browser can reveal only its own page canvas. Do not add redundant transparency helper copy or a matching title tooltip.

## Status and time

Green means normal work, inspection, handoff progression or completion. Amber means an explicit wait, pause or unconfirmed start; red means a recorded fault or troubleshooting. Blue is reserved for explicitly evidenced deliberation, never the default work color. Exact text accompanies every state. “Working” needs an authored work/check event or a matching accepted TRANSPORT_STARTED receipt; TOKEN ownership alone never creates it. The receipt author is the sender, so the corresponding message-bound TOKEN identifies the recipient.

Formal pause-request, paused, and resumed lifecycle events remain visible despite later administrative role registration. `D2_PASSED` means acceptance passed with closure still pending. `D1_FAILED` remains a failure requiring guidance; a later accepted Supervisor start displays troubleshooting. `REWORK_REQUESTED` means remediation is arranged; an accepted Worker start proves the next work phase. Overwatcher anomalies or overdue cadence mean attention is needed, not that the observer paused.

Total and current CELL work time are unions of recorded active intervals. Candidate submission, inspection result, blocker, and resource-contention boundaries stop the relevant interval; waiting does not accumulate.

## States and motion

Loading, unconfigured, empty, unsupported-schema, and read-error states occupy the same compact shell. A transient failure keeps the last good snapshot and marks it stale. The only motion is the short disclosure-chevron rotation, disabled under reduced-motion preference.

## Integration boundary

The React view and Rust read core remain standalone and do not import LCaS. A future LCaS rc.08/rc.09 panel may host the same read components without changing the SQLite authority or allowing BI writes.
