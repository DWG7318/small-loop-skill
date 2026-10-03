import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_bi_message_catalog_exactly_covers_state_core_event_and_observation_types():
    model = (ROOT / "crates" / "slk-state-core" / "src" / "model.rs").read_text(
        encoding="utf-8"
    )
    catalog = (ROOT / "apps" / "slk-bi" / "src" / "messages" / "catalog.ts").read_text(
        encoding="utf-8"
    )

    event_block = model.split("impl EventType", 1)[1].split("#[derive", 1)[0]
    observation_block = model.split("impl ObservationKind", 1)[1].split("#[derive", 1)[0]
    state_types = set(re.findall(r'=> "([A-Z][A-Z0-9_]+)"', event_block))
    state_observations = set(
        re.findall(r'=> "([A-Z][A-Z0-9_]+)"', observation_block)
    )

    event_seed_block = catalog.split("const EVENT_SEEDS", 1)[1].split(
        "const OBSERVATION_SEEDS", 1
    )[0]
    observation_seed_block = catalog.split("const OBSERVATION_SEEDS", 1)[1].split(
        "function entries", 1
    )[0]
    catalog_types = set(re.findall(r'\["([A-Z][A-Z0-9_]+)"', event_seed_block))
    catalog_observations = set(
        re.findall(r'\["([A-Z][A-Z0-9_]+)"', observation_seed_block)
    )

    assert catalog_types == state_types
    assert catalog_observations == state_observations
    assert "进度变化" not in catalog


def test_webbi_d1_upserts_cannot_replace_a_newer_run_snapshot():
    store = (ROOT / "apps" / "slk-bi" / "src" / "webbi" / "d1Store.ts").read_text(
        encoding="utf-8"
    )
    assert "WHERE excluded.updated_at > runs.updated_at" in store
    assert "WHERE excluded.last_seen_at > devices.last_seen_at" in store


def test_webbi_d1_migration_is_valid_sql_and_has_no_delete_path():
    store = (ROOT / "apps" / "slk-bi" / "src" / "webbi" / "d1Store.ts").read_text(
        encoding="utf-8"
    )
    migration = (
        ROOT / "apps" / "slk-bi" / "webbi" / "migrations" / "0001.sql"
    ).read_text(encoding="utf-8")
    database = sqlite3.connect(":memory:")
    database.executescript(migration)
    tables = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"devices", "runs", "messages", "notification_settings", "notification_deliveries"} <= tables
    assert "DELETE FROM" not in store.upper()
