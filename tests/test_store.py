"""The vessel store: merging two message types, expiry, and what it refuses.

Nothing here sleeps. The store takes an injected clock, so every time sensitive
case sets its own `now`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server.store import VesselStore
from helpers import CAPTURE_DAY, message, position, static

T0 = "2026-09-14 06:00:00.0 +0000 UTC"
T1 = "2026-09-14 06:01:00.0 +0000 UTC"
NOW = datetime(2026, 9, 14, 6, 5, tzinfo=timezone.utc)
MMSI = 533012345


# --- merging -----------------------------------------------------------------

def test_position_then_static_merges_into_one_record():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(MMSI, when=T0, name="TEST VESSEL"))
    store.ingest(static(MMSI, when=T1))
    records = store.records(now=NOW)
    assert len(records) == 1
    rec = records[0]
    assert rec["name"] == "TEST VESSEL"
    assert rec["lat"] == 3.0                 # from the position
    assert rec["type"] == "Cargo"            # from the static data
    assert rec["length_m"] == 180
    assert rec["destination"] == "MYPKG"


def test_static_then_position_also_merges():
    """S02's checks only ever covered one order. This is the other one."""
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(static(MMSI, when=T0))
    store.ingest(position(MMSI, when=T1, name="TEST VESSEL"))
    records = store.records(now=NOW)
    assert len(records) == 1
    rec = records[0]
    assert rec["type"] == "Cargo"
    assert rec["lat"] == 3.0
    assert rec["name"] == "TEST VESSEL"


def test_a_later_position_replaces_an_earlier_one():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(MMSI, when=T0, lat=3.0, lon=101.4))
    store.ingest(position(MMSI, when=T1, lat=3.5, lon=101.9))
    rec = store.records(now=NOW)[0]
    assert (rec["lat"], rec["lon"]) == (3.5, 101.9)


def test_a_name_once_learned_is_not_lost_by_a_later_nameless_message():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(MMSI, when=T0, name="TEST VESSEL"))
    store.ingest(position(MMSI, when=T1, name=""))
    assert store.records(now=NOW)[0]["name"] == "TEST VESSEL"


# --- expiry ------------------------------------------------------------------

def test_an_entry_is_present_before_max_age_and_gone_after():
    store = VesselStore(max_age=timedelta(minutes=2))
    store.ingest(position(MMSI, when=T0))
    assert len(store.records(now=datetime(2026, 9, 14, 6, 1, tzinfo=timezone.utc))) == 1
    assert len(store.records(now=NOW)) == 0


def test_prune_removes_expired_entries_and_reports_how_many():
    store = VesselStore(max_age=timedelta(minutes=2))
    store.ingest(position(MMSI, when=T0))
    store.ingest(position(533099999, when=T0))
    assert store.prune(now=NOW) == 2
    assert len(store) == 0


def test_position_age_is_reported_in_seconds():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(MMSI, when=T0))
    assert store.records(now=NOW)[0]["position_age_seconds"] == 300


# --- what it refuses ---------------------------------------------------------

def test_a_message_flagged_invalid_is_not_stored():
    """G8. The transmitter itself said the data is bad."""
    store = VesselStore()
    bad = position(MMSI)
    bad["Message"]["PositionReport"]["Valid"] = False
    assert store.ingest(bad) is False
    assert len(store) == 0


@pytest.mark.parametrize("junk", [
    None, 42, "a string", [], {},
    {"MessageType": "SubscriptionConfirmation", "Message": {}},
    {"MessageType": "PositionReport"},                       # no Message body
    {"MessageType": "PositionReport", "Message": {"PositionReport": {}}},  # no MetaData
])
def test_rubbish_is_rejected_without_raising(junk):
    store = VesselStore()
    assert store.ingest(junk) is False
    assert len(store) == 0


def test_an_unknown_message_type_is_not_stored():
    store = VesselStore()
    assert store.ingest(message("BaseStationReport", MMSI)) is False


# --- stations that are not ships ---------------------------------------------

def test_an_aid_to_navigation_is_held_but_not_returned_as_a_vessel():
    """S02: the feed carries buoys. They are not answers to a question about ships."""
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(995331385, when=T0))
    assert len(store) == 1                     # it was ingested
    assert store.records(now=NOW) == []        # but it is not a vessel
    assert store.counts(now=NOW)["not_a_ship"] == 1


def test_counts_separates_vessels_from_everything_else():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(position(533012345, when=T0))     # a ship
    store.ingest(position(995331385, when=T0))     # an aid to navigation
    store.ingest(static(533077889, when=T0))       # identity but no position
    counts = store.counts(now=NOW)
    assert counts == {"total": 3, "expired": 0, "no_position": 1,
                      "not_a_ship": 1, "vessels": 1}


# --- position optional lookups ----------------------------------------------

def test_a_vessel_with_identity_but_no_position_is_excluded_by_default():
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(static(MMSI, when=T0))
    assert store.records(now=NOW) == []


def test_it_is_included_when_a_position_is_not_required():
    """S02 D-4: AIS often gives a ship's name before its whereabouts."""
    store = VesselStore(max_age=timedelta(hours=1))
    store.ingest(static(MMSI, when=T0))
    records = store.records(now=NOW, require_position=False)
    assert len(records) == 1
    rec = records[0]
    assert rec["type"] == "Cargo"
    assert rec["lat"] is None
    assert rec["position_age_seconds"] is None, "must not fabricate an age"


# --- the real fixture --------------------------------------------------------

def test_the_captured_fixture_produces_a_known_vessel_count(filled_store):
    """Pinned deliberately. A mapping change that alters this should have to
    update the number on purpose rather than pass quietly."""
    counts = filled_store.counts(now=CAPTURE_DAY)
    assert counts["vessels"] == 89
    assert counts["not_a_ship"] == 3
    assert counts["no_position"] == 8
    assert counts["total"] == 100


def test_every_fixture_record_has_the_full_key_set(filled_store):
    expected = {"mmsi", "name", "type", "flag", "lat", "lon", "speed_knots",
                "course_degrees", "heading_degrees",
                "length_m", "destination", "nearest_port", "status",
                "position_age_seconds"}
    for rec in filled_store.records(now=CAPTURE_DAY):
        assert set(rec) == expected


def test_a_real_vessel_from_the_fixture_resolves_correctly(filled_store):
    """ALS CERES, captured on 2026-09-14. Type 70, A=194 B=61, MID 563."""
    by_mmsi = {r["mmsi"]: r for r in
               filled_store.records(now=CAPTURE_DAY, require_position=False)}
    als = by_mmsi["563186500"]
    assert als["name"] == "ALS CERES"
    assert als["type"] == "Cargo"
    assert als["flag"] == "Singapore"
    assert als["length_m"] == 255
    assert als["destination"] == "MYTTP"
