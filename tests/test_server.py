"""The server: the source seam, provenance, and what the tools return.

Tools return JSON strings, so every test parses and asserts values inside.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from maritime_mcp_server import server as S
from maritime_mcp_server.store import VesselStore
from helpers import CAPTURE_DAY, position, static


@pytest.fixture(autouse=True)
def no_store_by_default():
    """Every test starts from snapshot mode and leaves it that way."""
    S.set_store(None)
    yield
    S.set_store(None)


def parse(raw):
    return json.loads(raw)


# --- provenance --------------------------------------------------------------

def test_every_tool_reports_the_snapshot_source_when_there_is_no_store():
    for raw in (S.search_vessels(), S.vessels_near_port("Port Klang"),
                S.vessel_details("Seri Alam"), S.all_vessels()):
        data = parse(raw)["data"]
        assert data["source"] == "snapshot"
        assert data["vessel_count"] == 18
        assert data["snapshot_date"] == "2026-07-20"
        assert "not reflect where these vessels are now" in data["note"]


def test_the_error_path_still_carries_provenance():
    """An error is still an answer, and it can still be from stale data."""
    out = parse(S.vessel_details("no such ship"))
    assert "error" in out
    assert out["data"]["source"] == "snapshot"


def test_a_filled_store_switches_the_source_to_live(filled_store):
    S.set_store(filled_store)
    out = parse(S.search_vessels())
    assert out["data"]["source"] == "live"
    assert out["data"]["vessel_count"] > 18
    assert "oldest_position_age_seconds" in out["data"]


def test_an_empty_store_falls_back_to_the_snapshot():
    S.set_store(VesselStore(max_age=timedelta(seconds=0)))
    out = parse(S.search_vessels())
    assert out["data"]["source"] == "snapshot"
    assert out["matches"] == 18


def test_a_store_whose_entries_have_all_expired_falls_back(filled_store):
    """The fixture is historical, so a default max_age evicts everything."""
    S.set_store(filled_store)
    filled_store._max_age = timedelta(seconds=1)
    out = parse(S.search_vessels())
    assert out["data"]["source"] == "snapshot"


# --- nearest port ------------------------------------------------------------

def test_nearest_port_is_computed_for_live_records():
    """AC-9. S02's plan promised this field and never implemented it; the
    criterion passed because it only checked the key existed."""
    store = VesselStore(max_age=timedelta(days=3650))
    # A position a few miles off Port Klang, which sits at 3.00N 101.36E.
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=3.01, lon=101.37, name="NEAR KLANG"))
    S.set_store(store)
    vessels = parse(S.search_vessels())["vessels"]
    assert vessels[0]["nearest_port"] == "Port Klang"


def test_nearest_port_picks_the_actually_nearest_one():
    store = VesselStore(max_age=timedelta(days=3650))
    # Off Tanjung Pelepas, 1.36N 103.54E, far from Port Klang.
    store.ingest(position(563000001, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=1.30, lon=103.60, name="NEAR TP"))
    S.set_store(store)
    assert parse(S.search_vessels())["vessels"][0]["nearest_port"] == "Tanjung Pelepas"


def test_a_vessel_without_a_position_has_no_nearest_port():
    store = VesselStore(max_age=timedelta(days=3650))
    store.ingest(static(533012345, when="2026-09-14 06:00:00.0 +0000 UTC"))
    S.set_store(store)
    out = parse(S.vessel_details("533012345"))
    assert out["vessel"]["nearest_port"] is None


# --- search ------------------------------------------------------------------

def test_search_filters_are_case_insensitive_and_partial():
    out = parse(S.search_vessels(vessel_type="tank", status="at anchor"))
    assert out["matches"] >= 1
    assert all("Tanker" in v["type"] for v in out["vessels"])


def test_search_with_no_arguments_returns_everything():
    assert parse(S.search_vessels())["matches"] == 18


def test_search_tolerates_null_fields_on_live_records():
    """Live vessels often have no type at all. The pre-S02 code raised here."""
    store = VesselStore(max_age=timedelta(days=3650))
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC"))
    S.set_store(store)
    out = parse(S.search_vessels(vessel_type="Cargo"))
    assert out["matches"] == 0          # no type, so no match, and no exception


def test_a_search_that_matches_nothing_returns_an_empty_list_not_an_error():
    out = parse(S.search_vessels(flag="Narnia"))
    assert out["matches"] == 0
    assert out["vessels"] == []
    assert "error" not in out


# --- near port ---------------------------------------------------------------

def test_an_unknown_port_returns_an_error_naming_the_known_ones():
    out = parse(S.vessels_near_port("Nowhere"))
    assert "Unknown port" in out["error"]
    for port in ("port klang", "penang", "langkawi"):
        assert port in out["error"]


def test_results_are_sorted_nearest_first():
    out = parse(S.vessels_near_port("Port Klang", radius_nm=100))
    distances = [v["distance_nm"] for v in out["vessels"]]
    assert distances == sorted(distances)


def test_a_smaller_radius_returns_fewer_vessels():
    wide = parse(S.vessels_near_port("Port Klang", radius_nm=100))["matches"]
    narrow = parse(S.vessels_near_port("Port Klang", radius_nm=5))["matches"]
    assert narrow < wide


def test_vessels_without_a_position_are_excluded_from_distance_results():
    store = VesselStore(max_age=timedelta(days=3650))
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC", lat=3.01, lon=101.37))
    store.ingest(static(533077889, when="2026-09-14 06:00:00.0 +0000 UTC"))
    S.set_store(store)
    out = parse(S.vessels_near_port("Port Klang", radius_nm=50))
    assert out["matches"] == 1
    assert all(v["lat"] is not None for v in out["vessels"])


def test_a_negative_radius_currently_returns_nothing(monkeypatch):
    """Recording current behaviour, not endorsing it.

    There is no input validation yet; that is milestone goal G3. A negative
    radius quietly returns an empty list where an error would be more honest.
    This test exists so that when validation lands, it has to be updated
    deliberately.
    """
    out = parse(S.vessels_near_port("Port Klang", radius_nm=-5))
    assert out["matches"] == 0
    assert "error" not in out


# --- details -----------------------------------------------------------------

def test_lookup_by_exact_mmsi():
    out = parse(S.vessel_details("477055221"))
    assert out["vessel"]["name"] == "Kowloon Express"


def test_lookup_by_partial_name_is_case_insensitive():
    assert parse(S.vessel_details("kowloon"))["vessel"]["mmsi"] == "477055221"


def test_an_ambiguous_name_returns_candidates_rather_than_a_guess():
    out = parse(S.vessel_details("Seri"))
    assert "matched" in out["error"]
    assert len(out["candidates"]) > 1
    assert all({"mmsi", "name"} == set(c) for c in out["candidates"])


def test_a_vessel_with_identity_but_no_position_is_still_findable():
    """S02 D-4. A details lookup does not need a position."""
    store = VesselStore(max_age=timedelta(days=3650))
    store.ingest(static(533012345, when="2026-09-14 06:00:00.0 +0000 UTC"))
    S.set_store(store)
    out = parse(S.vessel_details("533012345"))
    assert out["vessel"]["type"] == "Cargo"
    assert out["vessel"]["lat"] is None


# --- resource ----------------------------------------------------------------

def test_the_resource_returns_every_vessel_with_provenance():
    out = parse(S.all_vessels())
    assert out["data"]["source"] == "snapshot"
    assert len(out["vessels"]) == 18


def test_the_resource_follows_the_live_store(filled_store):
    S.set_store(filled_store)
    out = parse(S.all_vessels())
    assert out["data"]["source"] == "live"
    assert len(out["vessels"]) == 89


# --- vessel_track -------------------------------------------------------------

@pytest.fixture
def history_server():
    """Server wired to an in-memory history, torn down cleanly."""
    from datetime import timedelta as _td
    from maritime_mcp_server.history import VesselHistory

    h = VesselHistory(path=":memory:")
    store = VesselStore(max_age=_td(days=3650), history=h)
    S.set_store(store)
    S.set_history(h)
    yield store, h
    S.set_store(None)
    S.set_history(None)
    h.close()


def test_track_returns_the_positions_that_were_recorded(history_server):
    """AC-7."""
    store, _ = history_server
    for minute, lat in ((0, 3.00), (1, 3.05), (2, 3.10)):
        store.ingest(position(533012345, when=f"2026-09-14 06:0{minute}:00.0 +0000 UTC",
                              lat=lat, lon=101.3, name="MOVER"))
    out = parse(S.vessel_track("533012345", hours=24 * 365 * 10))
    assert [p["lat"] for p in out["track"]] == [3.00, 3.05, 3.10]
    assert out["data"]["position_count"] == 3


def test_track_of_an_unknown_mmsi_is_empty_rather_than_an_error(history_server):
    out = parse(S.vessel_track("999999999", hours=24))
    assert out["track"] == []
    assert "error" not in out


def test_track_resolves_a_name_the_way_the_other_tools_do(history_server):
    store, _ = history_server
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=3.0, lon=101.3, name="KOWLOON EXPRESS"))
    out = parse(S.vessel_track("kowloon", hours=24 * 365 * 10))
    assert out["data"]["mmsi"] == "533012345"
    assert len(out["track"]) == 1


def test_track_says_so_when_a_name_matches_nothing(history_server):
    out = parse(S.vessel_track("no such ship", hours=24))
    assert "error" in out
    assert out["track"] == []


def test_track_states_that_gaps_are_real(history_server):
    """A caller must not read the list as a continuous path."""
    store, _ = history_server
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=3.0, lon=101.3, name="GAPPY"))
    out = parse(S.vessel_track("533012345", hours=24 * 365 * 10))
    assert "interpolated" in out["data"]["note"]


def test_track_without_history_configured_reports_that_plainly():
    S.set_history(None)
    out = parse(S.vessel_track("533012345", hours=24))
    assert out["track"] == []
    assert "not enabled" in out["error"]
