# Product

## Identity

**LE BI** is the compact, read-only desktop view of machine-wide SLK state. Its primary user is the Owner overseeing concurrent SLK Runs; other Agents consume the same read projections through `slk-bi-query`.

## Product purpose

The main surface shows only SLK Runs. Each row answers: which project and Run is this, when did it start, how much CELL work is complete, how much active work time was recorded, who owns the next action, and which SLK version is in use. Expanding a row reveals that SLK's Supervisor, Checker, Worker, and registered Overwatcher identities and model choices, Overwatcher assurance facts, and medium-detail CELL records.

Only one Run is expanded across the active list and archive. Both share one outer scrolling surface with a five-Run-header budget; the selected detail body adds height separately. Within that body, only CELL records scroll, with at most six visible rows and the newest execution record first. Screen work-area constraints may show fewer rows, but never discard records. Role and Overwatcher facts remain outside the CELL scroller.

An SLK may be independent or belong to a CLK/GLK project. That origin is a grouping dimension, not a second execution hierarchy in BI: LE BI never renders Chain, Node, Fusion, or DAG internals. Runs from the same independent project or CLK/GLK parent receive the same stable quiet tint and retain an explicit source label.

Completed, abandoned, and superseded SLKs leave the active surface immediately and remain readable in the archive, even when their parent CLK/GLK project continues.

## Boundaries

- BI reads the same SQLite authority as Agent queries and keeps no second state.
- Only Supervisor, Checker, and Worker write Run facts; Owner, Overwatcher, other Agents, and BI remain read-only.
- BI does not dispatch, approve, inspect, repair communication, or prove real-time liveness.
- Waiting time is excluded from displayed work duration; only recorded active Worker/Checker/Supervisor intervals count.
- The public SLK hierarchy is `Run → CELL`; legacy state grouping remains an internal compatibility detail.

## Product character

Compact, factual, and calm, with the restrained feel of a 1990s engineering calculator: muted LCD surfaces, monospaced data, segmented progress, thin rules, and small beveled controls. No command-center spectacle, card grid, decorative telemetry, or fake live animation.

## Accessibility

All status meaning has text as well as color or shape. Rows, both scrolling surfaces, and window controls are keyboard reachable with visible focus. The surface supports reduced motion, zoom-safe text, and a minimum 720 px desktop width with the SLK version retained. Height follows the complete content border box within the current monitor's work area, accounting for window position and display scale, and shrinks directly on collapse.
