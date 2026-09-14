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


# --- how far the nearest port actually is -------------------------------------
#
# Naming the closest of five ports spread along the whole coast reads as "at
# this port". Measured against a live feed of 230 vessels the median was 19.5 nm
# away and the furthest 37.9 nm, so the distance is reported with the name (G8).


def test_nearest_port_reports_the_distance_with_the_name():
    store = VesselStore(max_age=timedelta(days=3650))
    # Port Klang sits at 3.00N 101.36E. This is a little under 1 nm north east.
    store.ingest(position(533012345, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=3.01, lon=101.37, name="NEAR KLANG"))
    S.set_store(store)
    vessel = parse(S.search_vessels())["vessels"][0]
    assert vessel["nearest_port"] == "Port Klang"
    assert 0 < vessel["nearest_port_nm"] < 1


def test_a_distant_vessel_is_still_named_but_the_distance_says_otherwise():
    """The failure this story exists to fix: a label that reads as proximity."""
    store = VesselStore(max_age=timedelta(days=3650))
    # Mid strait, roughly 40 nm off Tanjung Pelepas at 1.36N 103.54E.
    store.ingest(position(563000002, when="2026-09-14 06:00:00.0 +0000 UTC",
                          lat=1.90, lon=103.10, name="MID STRAIT"))
    S.set_store(store)
    vessel = parse(S.search_vessels())["vessels"][0]
    assert vessel["nearest_port"] is not None
    assert vessel["nearest_port_nm"] > 30


def test_a_vessel_without_a_position_has_no_port_distance():
    store = VesselStore(max_age=timedelta(days=3650))
    store.ingest(static(533012345, when="2026-09-14 06:00:00.0 +0000 UTC"))
    S.set_store(store)
    vessel = parse(S.vessel_details("533012345"))["vessel"]
    assert vessel["nearest_port"] is None
    assert vessel["nearest_port_nm"] is None


def test_snapshot_records_carry_a_port_distance_too():
    """Snapshot and live answer the same questions in the same shape."""
    vessels = parse(S.search_vessels())["vessels"]
    assert vessels, "snapshot mode should return the bundled sample"
    for vessel in vessels:
        assert vessel["nearest_port"] is not None
        assert vessel["nearest_port_nm"] is not None


def test_port_name_and_distance_are_null_together_and_never_apart():
    """The contract in one assertion, across every snapshot record."""
    for vessel in parse(S.search_vessels())["vessels"]:
        assert (vessel["nearest_port"] is None) == (vessel["nearest_port_nm"] is None)
