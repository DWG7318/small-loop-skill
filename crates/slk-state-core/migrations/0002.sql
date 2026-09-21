ALTER TABLE runs ADD COLUMN run_name TEXT NOT NULL DEFAULT '';
ALTER TABLE runs ADD COLUMN slk_version TEXT NOT NULL DEFAULT 'unrecorded';
ALTER TABLE runs ADD COLUMN archive_reason TEXT;
ALTER TABLE runs ADD COLUMN archived_at TEXT;
ALTER TABLE runs ADD COLUMN superseded_by_run_id TEXT;

UPDATE runs
SET run_name = COALESCE(
    NULLIF((
        SELECT go_nodes.title
        FROM go_nodes
        WHERE go_nodes.run_id = runs.run_id
        ORDER BY go_nodes.ordinal
        LIMIT 1
    ), ''),
    goal
);

UPDATE runs SET slk_version = '4.0.0' WHERE slk_version = 'unrecorded';
UPDATE runs
SET archive_reason = 'completed', archived_at = closed_at
WHERE closure_state = 'closed' AND closed_at IS NOT NULL;

CREATE INDEX runs_primary_surface
ON runs(project_id, closure_state, created_at DESC);

