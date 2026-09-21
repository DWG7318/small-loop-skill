# LE BI Compact SLK Surface

LE BI shows only SLK Runs. A Run may be independent or belong to a CLK/GLK project; CLK and GLK are source context, not additional execution rows or diagrams.

The active view contains one calculator-like horizontal row per open SLK. Each row shows start date, source/project, concise Run name and description, confirmed working time, segmented CELL progress, current status, and SLK version. Opening a row reveals only its Supervisor/Checker/Worker identities and its CELL ledger.

Completed, abandoned, and explicitly superseded SLKs move to the archive immediately, independent of their parent CLK/GLK lifecycle. Multiple open SLKs may belong to the same repository or parent project; creating one must not archive another.

Rows from the same CLK or GLK parent share a very light stable tint while retaining an explicit source label. Independent Runs use the neutral tint. Color never replaces the source text.

The frameless Tauri shell has four embedded controls: archive, always-on-top, minimize, and red close. The header is draggable. Height follows content up to a bounded scroll region; maximize and resize are unavailable.

Working time is derived only from authored Worker, Checker, and Supervisor work intervals and excludes waiting. The BI remains read-only and never claims live work from stale state.
