ALTER TABLE runs ADD COLUMN run_description TEXT NOT NULL DEFAULT '';
ALTER TABLE runs ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'solo';
ALTER TABLE runs ADD COLUMN source_project_name TEXT;

CREATE INDEX runs_source_context
ON runs(source_kind, source_project_name, created_at DESC);
