"""Durable history: what gets written, what survives a restart, what is dropped.

Every store here is built over an in-memory database, so no test touches disk
and none can leave a file in the repository.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server import ais_mapping
from maritime_mcp_server.history import (
    DB_PATH_VAR,
    DEFAULT_HISTORY_DAYS,
    HISTORY_DAYS_VAR,
    VesselHistory,
    default_db_path,
    history_days,
)
from maritime_mcp_server.store import VesselStore
from helpers import position, static

DAY = "2026-09-14 06:00:00.0 +0000 UTC"
WHEN = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def history():
    h = VesselHistory(path=":memory:")
    yield h
    h.close()


def store_with(history, max_age=timedelta(days=3650)):
    return VesselStore(max_age=max_age, history=history)


# --- what gets written -------------------------------------------------------

def test_a_position_message_is_recorded(history):
    """AC-1."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.01, lon=101.37, name="NEAR KLANG"))
    assert history.count_positions() == 1


def test_the_recorded_position_holds_what_ais_reported(history):
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.01, lon=101.37, name="NEAR KLANG"))
    row = history.track("533012345", WHEN - timedelta(hours=1))[0]
    assert row["lat"] == 3.01
    assert row["lon"] == 101.37


def test_identity_is_upserted_not_duplicated(history):
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="FIRST"))
    store.ingest(position(533012345, when=DAY, lat=3.1, lon=101.4, name="FIRST"))
    conn = history._connect()
    assert conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0] == 1
    assert history.count_positions() == 2


def test_a_later_message_does_not_blank_what_an_earlier_one_taught(history):
    """AIS sends identity in pieces, so a name-only message must not erase type."""
    store = store_with(history)
    store.ingest(static(533012345, when=DAY))
    before = history._connect().execute(
        "SELECT type FROM vessels WHERE mmsi='533012345'").fetchone()[0]
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="LATER NAME"))
    after = history._connect().execute(
        "SELECT type, name FROM vessels WHERE mmsi='533012345'").fetchone()
    assert after[0] == before
    assert after[1] == "LATER NAME"


# Deliberately not tested here: that the AIS speed sentinel never reaches
# history. It cannot, because _write_history maps through position_fields, but
# that clearing arrived in S06 which is not merged and not on this branch. A
# test for it would assert another story's behaviour and could not pass here.
# Worth adding once S06 lands.


# --- the hot path stays off disk ---------------------------------------------

def test_records_reads_nothing_from_the_database(history, raw_messages):
    """AC-3. Counted, not timed, so it cannot flake."""
    store = store_with(history)
    for message in raw_messages:
        store.ingest(message)

    conn = history._connect()
    queries = []
    conn.set_trace_callback(queries.append)
    try:
        store.records(now=WHEN + timedelta(minutes=1))
    finally:
        conn.set_trace_callback(None)

    assert queries == []


def test_records_returns_the_same_values_with_history_as_without(raw_messages):
    """AC-2. History is additive: it must not change a single answer."""
    plain = VesselStore(max_age=timedelta(days=3650))
    h = VesselHistory(path=":memory:")
    backed = VesselStore(max_age=timedelta(days=3650), history=h)
    try:
        for message in raw_messages:
            plain.ingest(message)
            backed.ingest(message)
        now = WHEN + timedelta(minutes=1)
        assert backed.records(now=now) == plain.records(now=now)
    finally:
        h.close()


# --- surviving a restart -----------------------------------------------------

def test_a_new_store_over_an_existing_database_already_knows_the_fleet(history):
    """AC-4. The whole point: a restart costs nothing."""
    first = store_with(history)
    first.ingest(position(533012345, when=DAY, lat=3.01, lon=101.37, name="BUNGA MAS"))

    # A brand new store, as if the process had been restarted.
    revived = VesselStore(max_age=timedelta(days=3650), history=history)
    records = revived.records(now=WHEN + timedelta(minutes=1))

    assert [r["mmsi"] for r in records] == ["533012345"]
    assert records[0]["lat"] == 3.01


def test_a_restored_vessel_keeps_its_name_and_type(history):
    store = store_with(history)
    store.ingest(static(533012345, when=DAY))
    store.ingest(position(533012345, when=DAY, lat=3.01, lon=101.37, name="BUNGA MAS"))

    revived = VesselStore(max_age=timedelta(days=3650), history=history)
    record = revived.records(now=WHEN + timedelta(minutes=1))[0]
    assert record["name"] == "BUNGA MAS"
    assert record["type"] is not None


def test_a_restored_position_is_reported_with_its_real_age(history):
    """Restored is not fresh, and the record must not pretend otherwise."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="OLD FIX"))

    revived = VesselStore(max_age=timedelta(days=3650), history=history)
    record = revived.records(now=WHEN + timedelta(minutes=20))[0]
    assert record["position_age_seconds"] == 20 * 60


def test_a_live_message_wins_over_what_was_restored(history):
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="OLD"))

    revived = VesselStore(max_age=timedelta(days=3650), history=history)
    revived.ingest(position(533012345, when="2026-09-14 06:30:00.0 +0000 UTC",
                            lat=3.5, lon=101.9, name="NEW"))
    record = revived.records(now=WHEN + timedelta(hours=1))[0]
    assert record["lat"] == 3.5
    assert record["name"] == "NEW"


def test_nothing_outside_the_currency_window_is_restored(history):
    """A position older than max_age would be pruned a moment later anyway."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="ANCIENT"))

    revived = VesselStore(max_age=timedelta(minutes=30), history=history)
    assert revived.records(now=datetime.now(timezone.utc)) == []


# --- retention ---------------------------------------------------------------

def test_prune_drops_history_past_the_retention_window(history):
    """AC-5."""
    store = VesselStore(max_age=timedelta(days=3650), history=history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="OLD"))
    assert history.count_positions() == 1

    store.prune(now=WHEN + timedelta(days=DEFAULT_HISTORY_DAYS + 1))
    assert history.count_positions() == 0


def test_prune_keeps_history_inside_the_retention_window(history):
    store = VesselStore(max_age=timedelta(days=3650), history=history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="RECENT"))
    store.prune(now=WHEN + timedelta(days=1))
    assert history.count_positions() == 1


def test_currency_and_retention_are_different_questions(history):
    """AC-6. A vessel can be long gone from "now" and still have a past."""
    store = VesselStore(max_age=timedelta(minutes=30), history=history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="GONE"))

    later = WHEN + timedelta(hours=2)
    dropped = store.prune(now=later)

    assert dropped == 1, "the vessel is no longer current"
    assert history.count_positions() == 1, "but its history is kept"
    assert store.records(now=later) == []


# --- reading a track ---------------------------------------------------------

def test_track_returns_positions_oldest_first(history):
    store = store_with(history)
    for minute, lat in ((0, 3.0), (5, 3.1), (10, 3.2)):
        store.ingest(position(533012345, when=f"2026-09-14 06:{minute:02d}:00.0 +0000 UTC",
                              lat=lat, lon=101.3, name="MOVER"))
    track = history.track("533012345", WHEN - timedelta(hours=1))
    assert [p["lat"] for p in track] == [3.0, 3.1, 3.2]


def test_track_is_bounded_by_the_window(history):
    store = store_with(history)
    store.ingest(position(533012345, when="2026-09-14 05:00:00.0 +0000 UTC",
                          lat=1.0, lon=101.0, name="EARLY"))
    store.ingest(position(533012345, when=DAY, lat=2.0, lon=101.0, name="LATE"))
    track = history.track("533012345", WHEN - timedelta(minutes=30))
    assert [p["lat"] for p in track] == [2.0]


def test_track_of_an_unknown_vessel_is_empty_not_an_error(history):
    """AC-7. Nothing heard is a true answer, not a failure."""
    assert history.track("999999999", WHEN - timedelta(days=1)) == []


# --- where the file lives ----------------------------------------------------

def test_the_database_path_honours_the_environment(monkeypatch, tmp_path):
    """AC-8."""
    target = tmp_path / "somewhere" / "vessels.db"
    monkeypatch.setenv(DB_PATH_VAR, str(target))
    assert default_db_path() == str(target)


def test_the_default_path_is_never_inside_the_package(monkeypatch, tmp_path):
    """G3: an installed wheel is read-only, and a database there fails on write."""
    monkeypatch.delenv(DB_PATH_VAR, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    package_dir = os.path.dirname(ais_mapping.__file__)
    assert not default_db_path().startswith(package_dir)


def test_retention_is_configurable(monkeypatch):
    monkeypatch.setenv(HISTORY_DAYS_VAR, "7")
    assert history_days() == 7


def test_a_nonsense_retention_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv(HISTORY_DAYS_VAR, "not a number")
    assert history_days() == DEFAULT_HISTORY_DAYS


def test_a_zero_retention_would_delete_everything_so_it_is_refused(monkeypatch):
    monkeypatch.setenv(HISTORY_DAYS_VAR, "0")
    assert history_days() == DEFAULT_HISTORY_DAYS


# --- course and heading -------------------------------------------------------
#
# Where a vessel is going, and where its bow points. Never defaulted to 0:
# that is due north, a real heading, and inventing it would point a fleet the
# wrong way (G8).


def test_course_and_heading_are_recorded(history):
    """AC-1, AC-2, AC-6."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="STEERING",
                          Cog=87.5, TrueHeading=90))
    row = history.track("533012345", WHEN - timedelta(hours=1))[0]
    assert row["course_degrees"] == 87.5
    assert row["heading_degrees"] == 90


def test_the_course_and_heading_sentinels_are_stored_as_nothing(history):
    """AC-3."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="NO STEER",
                          Cog=360, TrueHeading=511))
    row = history.track("533012345", WHEN - timedelta(hours=1))[0]
    assert row["course_degrees"] is None
    assert row["heading_degrees"] is None


def test_a_missing_course_is_null_and_not_north(history):
    """AC-4. The distinction the whole story turns on."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="SILENT"))
    row = history.track("533012345", WHEN - timedelta(hours=1))[0]
    assert row["course_degrees"] is None
    assert row["heading_degrees"] is None


def test_due_north_survives_as_zero(history):
    """AC-5. Zero is a heading, not an absence, and must not be lost."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="NORTHBOUND",
                          Cog=0, TrueHeading=0))
    row = history.track("533012345", WHEN - timedelta(hours=1))[0]
    assert row["course_degrees"] == 0
    assert row["heading_degrees"] == 0


def test_a_restored_vessel_keeps_its_course(history):
    """AC-7."""
    store = store_with(history)
    store.ingest(position(533012345, when=DAY, lat=3.0, lon=101.3, name="STEERING",
                          Cog=180, TrueHeading=182))
    revived = VesselStore(max_age=timedelta(days=3650), history=history)
    record = revived.records(now=WHEN + timedelta(minutes=1))[0]
    assert record["course_degrees"] == 180
    assert record["heading_degrees"] == 182


def test_a_database_written_before_these_columns_still_opens(tmp_path):
    """AC-8 risk: an older database must migrate, not fail on first query."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE positions (mmsi TEXT NOT NULL, observed_at TEXT NOT NULL,"
        " lat REAL, lon REAL, sog REAL, status TEXT);"
        "CREATE TABLE vessels (mmsi TEXT PRIMARY KEY, name TEXT, type TEXT,"
        " flag TEXT, length_m REAL, destination TEXT, updated_at TEXT);"
    )
    old.execute("INSERT INTO positions (mmsi, observed_at, lat, lon, sog, status)"
                " VALUES ('533012345', '2026-09-14T06:00:00+00:00', 3.0, 101.3, 8.0, 'Moored')")
    old.commit()
    old.close()

    migrated = VesselHistory(path=str(path))
    try:
        row = migrated.track("533012345", WHEN - timedelta(days=1))[0]
        assert row["lat"] == 3.0, "the old row survives"
        assert row["course_degrees"] is None, "and has no course, rather than failing"
    finally:
        migrated.close()


def test_the_real_sentinel_fixture_yields_no_course(sentinel_messages, history):
    """AC-8. The captured message carried all three sentinels at once."""
    store = store_with(history)
    store.ingest(sentinel_messages[0])
    mmsi = str(sentinel_messages[0]["MetaData"]["MMSI"])
    rows = history.track(mmsi, datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert rows, "the message was ingested"
    assert rows[0]["speed_knots"] is None
    assert rows[0]["course_degrees"] is None
    assert rows[0]["heading_degrees"] is None
