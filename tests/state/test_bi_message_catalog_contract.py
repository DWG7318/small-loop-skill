import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).parents[2]
BI_ROOT = ROOT / "apps" / "slk-bi"


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
        "const SPECIALIZED_EVENT_SEEDS", 1
    )[0]
    specialized_event_seed_block = catalog.split(
        "const SPECIALIZED_EVENT_SEEDS", 1
    )[1].split(
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
    assert set(
        re.findall(r'\["([A-Z][A-Z0-9_]+)"', specialized_event_seed_block)
    ) == {"ROLE_CLOSED"}
    assert catalog_observations == state_observations
    assert "进度变化" not in catalog


def test_webbi_d1_upserts_cannot_replace_a_newer_run_snapshot():
    store = (BI_ROOT / "src" / "webbi" / "d1Store.ts").read_text(
        encoding="utf-8"
    )
    assert "WHERE excluded.last_seen_at > devices.last_seen_at" in store
    assert (
        "envelope.generated_at > (previous.source_generated_at ?? previous.updated_at)"
        in store
    )

    # Exercise the production CAS statement, not the obsolete updated_at gate.
    # Full source-revision/hash, sticky archive, correction, concurrent ingest and
    # reopen behavior runs against SQLite in src/webbi/closeoutPersistence.test.ts
    # (pnpm test -- src/webbi/closeoutPersistence.test.ts from apps/slk-bi).
    statement = re.search(r"`(INSERT INTO runs\b[^`]+)`", store)
    assert statement is not None
    with sqlite3.connect(":memory:") as database:
        database.execute("PRAGMA foreign_keys=ON")
        for name in ("0001.sql", "0002_receipts.sql"):
            database.executescript(
                (BI_ROOT / "webbi" / "migrations" / name).read_text(encoding="utf-8")
            )
        database.execute("INSERT INTO devices VALUES('device-a','A','t0','t0')")
        sql = statement.group(1)
        assert database.execute(
            sql, ("device-a", "run-a", 0, "old", "t1", None, "source-1")
        ).rowcount == 1
        assert database.execute(
            sql, ("device-a", "run-a", 1, "new", "t2", "old", "source-2")
        ).rowcount == 1
        # A delayed writer still holding 'old' cannot overwrite 'new', even with
        # later timestamps. The application must reread and merge before retry.
        assert database.execute(
            sql, ("device-a", "run-a", 0, "stale", "t9", "old", "source-9")
        ).rowcount == 0
        assert database.execute(
            "SELECT archived,payload_json,updated_at,source_generated_at FROM runs"
        ).fetchone() == (1, "new", "t2", "source-2")


def test_webbi_d1_migration_is_valid_sql_and_has_no_delete_path():
    store = (ROOT / "apps" / "slk-bi" / "src" / "webbi" / "d1Store.ts").read_text(
        encoding="utf-8"
    )
    database = sqlite3.connect(":memory:")
    database.execute("PRAGMA foreign_keys=ON")
    for name in ("0001.sql", "0002_receipts.sql"):
        database.executescript(
            (BI_ROOT / "webbi" / "migrations" / name).read_text(encoding="utf-8")
        )
    tables = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"devices", "runs", "messages", "notification_settings", "notification_deliveries"} <= tables
    assert "source_generated_at" in {
        row[1] for row in database.execute("PRAGMA table_info(runs)")
    }
    primary_key = sorted(
        (row[5], row[1])
        for row in database.execute("PRAGMA table_info(messages)")
        if row[5]
    )
    assert primary_key == [(1, "device_id"), (2, "run_id"), (3, "message_id")]
    assert database.execute("PRAGMA foreign_key_check").fetchall() == []
    database.close()
    assert "DELETE FROM" not in store.upper()
