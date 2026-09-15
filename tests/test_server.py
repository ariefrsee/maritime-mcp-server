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


def test_a_padded_filter_matches_the_same_vessels_as_an_unpadded_one():
    """S06, and the worst defect this story fixed: a stray space produced a
    confident wrong answer rather than an error. 7 vessels, not 0."""
    padded = parse(S.search_vessels(flag=" malaysia "))
    plain = parse(S.search_vessels(flag="malaysia"))
    assert padded["matches"] == plain["matches"] == 7
    assert [v["mmsi"] for v in padded["vessels"]] == [v["mmsi"] for v in plain["vessels"]]


def test_filters_are_normalised_for_case_and_padding_together():
    assert parse(S.search_vessels(flag="  MALAYSIA  "))["matches"] == 7


def test_a_whitespace_only_filter_means_no_filter():
    """AC-6. Consistent with an empty string, which already means no filter.
    A deliberate decision: the alternative is matching nothing, which is the
    behaviour this story removed elsewhere."""
    assert parse(S.search_vessels(flag="   "))["matches"] == 18
    assert parse(S.search_vessels(vessel_type="  ", status="  "))["matches"] == 18


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


async def _call(name, args):
    """Invoke a tool the way a client does, through the protocol layer."""
    return await S.mcp.call_tool(name, args)


@pytest.mark.anyio
@pytest.mark.parametrize("radius", [-5, 0, -0.1, 1000, 501])
async def test_an_out_of_range_radius_is_rejected_by_the_schema(radius):
    """S06. Before this, a negative radius returned an empty list, which is a
    claim about the sea rather than about the question."""
    with pytest.raises(Exception) as excinfo:
        await _call("vessels_near_port", {"port": "Port Klang", "radius_nm": radius})
    assert "radius_nm" in str(excinfo.value)


@pytest.mark.anyio
@pytest.mark.parametrize("radius", [0.1, 30, 500])
async def test_an_in_range_radius_is_accepted(radius):
    await _call("vessels_near_port", {"port": "Port Klang", "radius_nm": radius})


@pytest.mark.anyio
async def test_the_schema_publishes_the_radius_bounds():
    """AC-3. A client should learn the valid range without having to call."""
    tools = {t.name: t for t in await S.mcp.list_tools()}
    radius = tools["vessels_near_port"].input_schema["properties"]["radius_nm"]
    assert radius["exclusiveMinimum"] == 0
    assert radius["maximum"] == 500
    assert "nautical miles" in radius["description"]


@pytest.mark.anyio
async def test_every_tool_parameter_carries_a_description():
    """AC-7. The client reads these to decide how to call a tool, so a missing
    one makes bad calls more likely rather than merely less documented."""
    undocumented = []
    for tool in await S.mcp.list_tools():
        for name, prop in tool.input_schema["properties"].items():
            if not prop.get("description"):
                undocumented.append(f"{tool.name}.{name}")
    assert undocumented == []


def test_a_direct_python_call_bypasses_schema_validation():
    """Recording a real limitation, not endorsing it.

    The bounds live in the tool signature and are enforced by the protocol
    layer. Calling the function directly from Python skips that entirely, so a
    negative radius still returns an empty list here. No client calls these
    functions directly, but the smoke test does.
    """
    out = parse(S.vessels_near_port("Port Klang", radius_nm=-5))
    assert out["matches"] == 0
    assert "error" not in out


# --- details -----------------------------------------------------------------

@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  "])
def test_a_blank_query_asks_for_a_name_or_mmsi(blank):
    """S06. Before this it reported that your empty query matched 18 vessels
    and suggested being more specific, which is nonsense: you asked for nothing."""
    out = parse(S.vessel_details(blank))
    assert "required" in out["error"]
    assert "MMSI" in out["error"]
    assert out["data"]["source"] == "snapshot", "an error still carries provenance"
    assert "candidates" not in out


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


# --- response size ---

FIXTURE_NEAR = ("Tanjung Pelepas", 40)


def test_a_typical_response_is_not_dominated_by_formatting(filled_store):
    """S07. Before this story the same call returned 26,713 characters, of which
    29% was indentation carrying no information."""
    S.set_store(filled_store)
    raw = S.vessels_near_port(*FIXTURE_NEAR, limit=200)
    assert len(raw) < 15_000, f"uncapped response grew to {len(raw)} chars"
    assert '\n' not in raw, "responses must be serialised compactly, not indented"


def test_the_default_limit_keeps_a_busy_answer_small(filled_store):
    S.set_store(filled_store)
    raw = S.vessels_near_port(*FIXTURE_NEAR)
    assert len(raw) < 6_000, f"default response grew to {len(raw)} chars"


def test_coordinates_are_rounded_to_about_eleven_metres(filled_store):
    """Four decimals. AIS is nowhere near as precise as a float prints."""
    S.set_store(filled_store)
    for v in parse(S.search_vessels(limit=200))["vessels"]:
        if v["lat"] is None:
            continue
        assert len(str(v["lat"]).split(".")[-1]) <= 4, v["lat"]
        assert len(str(v["lon"]).split(".")[-1]) <= 4, v["lon"]


def test_rounding_moves_a_vessel_by_less_than_fifteen_metres(filled_store):
    """AC-3. Rounding is only acceptable if it is below the source's accuracy."""
    S.set_store(filled_store)
    raw_positions = {r["mmsi"]: (r["lat"], r["lon"])
                     for r in filled_store.records(now=CAPTURE_DAY)}
    for v in parse(S.search_vessels(limit=200))["vessels"]:
        if v["lat"] is None:
            continue
        lat0, lon0 = raw_positions[v["mmsi"]]
        # one degree of latitude is about 111 km; 0.0001 degrees is about 11 m
        assert abs(v["lat"] - lat0) * 111_000 < 15
        assert abs(v["lon"] - lon0) * 111_000 < 15


def test_unknown_values_are_still_null_not_absent(filled_store):
    """S02's promise survives S07. Absent would be a different claim: the
    server did not send this, rather than we do not know this."""
    S.set_store(filled_store)
    vessels = parse(S.search_vessels(limit=200))["vessels"]
    without_type = [v for v in vessels if v["type"] is None]
    assert without_type, "the fixture should contain vessels with no static data"
    assert "type" in without_type[0], "the key must be present, holding null"


# --- truncation ---

def test_a_capped_response_says_how_many_it_left_out(filled_store):
    """AC-6. A cap that truncates silently is worse than a large response."""
    S.set_store(filled_store)
    out = parse(S.vessels_near_port(*FIXTURE_NEAR, limit=5))
    assert out["matches"] == 67
    assert out["returned"] == 5
    assert len(out["vessels"]) == 5


def test_a_limit_larger_than_the_result_set_is_not_an_error(filled_store):
    S.set_store(filled_store)
    out = parse(S.vessels_near_port(*FIXTURE_NEAR, limit=200))
    assert out["matches"] == out["returned"] == 67


def test_truncation_keeps_the_nearest_vessels(filled_store):
    """Which five you get matters. Nearest first, not an arbitrary five."""
    S.set_store(filled_store)
    everything = parse(S.vessels_near_port(*FIXTURE_NEAR, limit=200))["vessels"]
    capped = parse(S.vessels_near_port(*FIXTURE_NEAR, limit=5))["vessels"]
    assert [v["mmsi"] for v in capped] == [v["mmsi"] for v in everything[:5]]


def test_search_also_reports_matched_and_returned(filled_store):
    S.set_store(filled_store)
    out = parse(S.search_vessels(limit=3))
    assert out["matches"] == 89
    assert out["returned"] == 3


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, -1, 201, 1000])
async def test_an_out_of_range_limit_is_rejected_by_the_schema(limit):
    with pytest.raises(Exception) as excinfo:
        await _call("vessels_near_port", {"port": "Port Klang", "limit": limit})
    assert "limit" in str(excinfo.value)


@pytest.mark.anyio
async def test_the_schema_publishes_the_limit_bounds():
    tools = {t.name: t for t in await S.mcp.list_tools()}
    for name in ("search_vessels", "vessels_near_port"):
        limit = tools[name].input_schema["properties"]["limit"]
        assert limit["exclusiveMinimum"] == 0
        assert limit["maximum"] == 200
        assert limit["default"] == 25


# --- redundant fields ---

def test_nearest_port_is_omitted_when_the_caller_named_a_port(filled_store):
    """Every vessel would carry the same value, which the caller already knows."""
    S.set_store(filled_store)
    for v in parse(S.vessels_near_port(*FIXTURE_NEAR))["vessels"]:
        assert "nearest_port" not in v
        assert "position_age_seconds" not in v


def test_nearest_port_is_present_when_no_port_was_named(filled_store):
    S.set_store(filled_store)
    vessels = parse(S.search_vessels(limit=200))["vessels"]
    assert all("nearest_port" in v for v in vessels)
    assert any(v["nearest_port"] for v in vessels)


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
