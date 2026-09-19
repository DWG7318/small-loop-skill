# SLK BI Design System

## Design direction

SLK BI is a compact desktop operations surface, not a marketing dashboard. It uses the same visual language as LCaS without depending on the LCaS repository: system sans typography, narrow information rails, quiet solid surfaces, a restrained periwinkle-blue accent, explicit semantic colors, and short state transitions.

Physical scene: an Owner reviews several engineering Runs for minutes at a time on a desktop monitor, often beside Codex and terminals, in either daytime or low-light conditions. Both light and dark themes are first-class.

Design settings:

- design variance: 3
- motion intensity: 2
- visual density: 8
- color strategy: restrained

## Foundations

### Typography

- UI: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`
- Data: `ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace`
- Scale: 12, 13, 14, and 16 px with 1.35 to 1.55 line height
- Headings remain compact; no display typography is used.

### Geometry

- Window: 12 px radius
- Main panels: 10 px radius
- Controls: 8 px radius
- Compact items: 6 px radius
- Pills are reserved for short semantic state labels.

### Spacing

Use a 4 px base with 4, 8, 12, 16, 20, 24, 32, and 48 px steps. Dense rows use 8 to 12 px vertical rhythm. Major panes use 16 to 24 px internal spacing.

### Color

Dark theme:

- app `#0d0d0d`
- navigation `#101010`
- content `#151515`
- raised `#1a1a1a`
- primary text `rgba(255,255,255,.92)`
- secondary text `rgba(255,255,255,.58)`
- accent `#8aa4ff`

Light theme:

- app `#f4f4f6`
- navigation `#ececef`
- content and raised `#ffffff`
- primary text `rgba(0,0,0,.88)`
- secondary text `rgba(0,0,0,.55)`
- accent `#3d5fd9`

Semantic color is reserved for proven state: success, warning, danger, and information. Every status also carries text and an icon or shape.

## Shell

The desktop shell uses three adjustable regions:

1. A 260 to 320 px project rail lists all projects and Runs, grouped by project. Each Run shows closure state, current responsibility role, and most recent fact time.
2. The flexible center pane shows the selected Run header, a serial GO/CELL track, current SLK TOKEN boundary, and factual timeline.
3. A 340 to 420 px inspector opens for selected GO, CELL, role, event, plan revision, or evidence. It can collapse without hiding the Run track.

The title bar contains global search, refresh state, theme, and data-root health. It contains no write action.

## Components

### Project rail

Projects are headings, not cards. Runs are compact rows with stable selection, keyboard navigation, and exact IDs available on demand. A real semantic state dot may appear once per Run row, paired with text.

### Run header

Shows project and Run name, Run ID, plan revision, current state, creation and closure time, and latest factual event. It avoids large metric tiles.

### Serial track

GO nodes form one vertical sequence. The selected GO expands its CELL sequence in ordinal order. Completed, current, planned, rework, exempted, and closed states use the same geometry and different semantic treatments. The track never draws parallel branches because SLK is linear.

### Responsibility strip

Shows the current TOKEN sequence, owner role, GO/CELL, message identity, accepted endpoint version, and handoff time. It distinguishes:

- responsibility transferred;
- work started but not yet delivered;
- candidate delivered for D1;
- D1 result delivered for D2;
- Run closed.

It does not claim process liveness. When state only proves that work began, the label is "Started, not delivered" with the last authored time.

### Role roster

Displays current and retired role instances, agent runtime, provider, model, reasoning level, session ID, endpoint version, replacement history, and session rebound history. Credentials and hashes never appear.

### Timeline

Events are ordered facts with author role, scope, attempt, plan revision, time, and detail. Corrections remain adjacent to the original fact and visibly preserve both records. Resource contention and recovery use environment wording and are not styled as D1 or D2 failures.

### Evidence

Evidence rows show type, scope, SHA-256, durable location, and verification state. File opening is a read-only operating-system action. Missing or mismatched evidence is explicit and never auto-repaired.

## States

- Loading uses layout-matched skeletons.
- An unconfigured computer explains where SLK state configuration is created, without offering a BI write action.
- An empty data root explains that no Run has been initialized.
- A read error preserves the last valid view, marks it stale, shows the exact safe error, and offers refresh.
- Unsupported future schema blocks interpretation and shows the found and supported versions.
- Deleted or missing evidence remains visible as a failed verification fact.

## Motion and interaction

Transitions are 120 to 200 ms and communicate selection, pane resize, or refreshed state. There are no page-load sequences, pulsing decorative indicators, automatic graph movement, or scrolling effects. Reduced-motion preference removes nonessential interpolation.

## Responsive behavior

The product is desktop-first. Below 980 px, the inspector becomes an overlay drawer and the project rail can collapse. Below 720 px, the interface remains inspectable in a single-column sequence but does not pretend to be a full mobile operations experience.

## Reuse boundary

SLK BI owns a small compatible token set and reusable React feature components. It does not import LCaS source or modify LCaS. A future LCaS rc.08 or rc.09 integration can host the feature components and call the same read projections without changing the SLK state authority.
