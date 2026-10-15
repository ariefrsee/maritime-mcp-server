"""The port board: who is at Port Dickson, who is coming, who has gone.

Most of these tests pin a boundary with literal values on both sides of it,
because the useful failures here are a ship moving to the wrong list by a
minute or a knot, not a crash (G29).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from maritime_mcp_server import port_board
from maritime_mcp_server.port_board import (
    build_board,
    compass_point,
    is_harbour_craft,
    is_unknown_type,
    matches_port,
    normalise_destination,
    port_aliases,
    residents,
    visits,
)

CENTRE = (2.52, 101.80)
RADIUS = 8.0
ALIASES = port_aliases("port dickson")
NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)

#: Inside the circle, about a mile off the centre, and well outside it.
IN = (2.50, 101.79)
OUT = (2.52 - 20 / 60, 101.80)  # 20 nm due south

FIXTURE = Path(__file__).parent / "data" / "port_dickson_tracks.json"


def at_nm(distance):
    """A position this many nautical miles due south of the centre."""
    return (2.52 - distance / 60, 101.80)


def fix(at, where=IN, sog=0.0, status="Under way using engine"):
    lat, lon = where
    return {"observed_at": at.isoformat(), "lat": lat, "lon": lon, "sog": sog,
            "status": status}


def hours(n=0, minutes=0):
    return NOW - timedelta(hours=n, minutes=minutes)


def board(fixes, identity=None, days=0, mmsi="111111111"):
    return build_board({mmsi: fixes}, {mmsi: identity or {}}, {mmsi: days},
                       CENTRE, RADIUS, ALIASES, NOW)


def listed(result, mmsi="111111111"):
    """Which lists a vessel appears in."""
    return sorted(name for name, rows in result.items()
                  if any(r["mmsi"] == mmsi for r in rows))


# --- the measured thresholds, asserted on their own -------------------------


def test_the_thresholds_are_the_ones_the_measurements_chose():
    assert port_board.VISIT_GAP_HOURS == 6
    assert port_board.EXIT_MARGIN_NM == 1.0
    assert port_board.AT_PORT_HOURS == 6
    assert port_board.HEADING_IN_HOURS == 12
    assert port_board.DEPARTED_HOURS == 48
    assert port_board.RESIDENT_DAYS == 10
    assert port_board.RESIDENT_WINDOW_DAYS == 14
    assert port_board.LOOKBACK_HOURS == 72
    assert port_board.BOARD_PORTS["port dickson"]["radius_nm"] == 8.0
    assert port_board.STOPPED_KNOTS == 0.5


# --- destinations (AC-1) ------------------------------------------------------


@pytest.mark.parametrize("declared", [
    "MY PDI", "PORT DICKSON", "PORTDICKSON", "MYPDI", "MY_PDI", "MY-PD",
    "MLY PDI", "MY_P.DICKSON", "GHJUB>MYPDI",
])
def test_every_spelling_seen_in_production_means_port_dickson(declared):
    assert matches_port(declared, ALIASES)


@pytest.mark.parametrize("declared", [
    "MYPKG", "PORT KLANG", "PDIX", "SPDI", "MYPID", "", "   ", None,
])
def test_near_misses_and_blanks_do_not(declared):
    assert not matches_port(declared, ALIASES)


def test_normalising_keeps_the_letters_after_the_last_arrow():
    assert normalise_destination("GHJUB>MYPDI") == "MYPDI"
    assert normalise_destination("sgsin => grpir") == "GRPIR"
    assert normalise_destination("MY_P.DICKSON") == "MYPDICKSON"
    assert normalise_destination(None) == ""


def test_the_alias_table_normalises_to_these_keys():
    assert ALIASES == {"MYPDI", "MYPD", "MLYPDI", "PDI", "PORTDICKSON",
                       "PDICKSON", "MYPDICKSON"}


# --- visits (AC-2, AC-3, AC-4) -----------------------------------------------


def test_fixes_5h59_apart_are_one_visit():
    found = visits([fix(hours(10)), fix(hours(10) + timedelta(hours=5, minutes=59))],
                   CENTRE, RADIUS)
    assert len(found) == 1


def test_fixes_6h01_apart_are_two_visits_and_the_second_opens_on_a_gap():
    found = visits([fix(hours(10)), fix(hours(10) + timedelta(hours=6, minutes=1))],
                   CENTRE, RADIUS)
    assert len(found) == 2
    assert found[0]["closed_by"] == "gap"
    assert found[1]["opened_by"] == "gap"


def test_a_fix_outside_splits_a_visit_into_departure_and_arrival():
    found = visits([fix(hours(5)), fix(hours(4), OUT), fix(hours(3))], CENTRE, RADIUS)
    assert [v["closed_by"] for v in found] == ["departure", None]
    assert found[0]["next_at"] == hours(4)
    assert found[1]["opened_by"] == "arrival"


def test_a_ship_working_along_the_edge_is_one_visit_not_two():
    # RAINA in the capture: 7.9 nm, then 8.0, then in to anchor at 3.9.
    found = visits([fix(hours(5), at_nm(7.9), 12.0), fix(hours(4, 50), at_nm(8.3), 11.0),
                    fix(hours(4), at_nm(6.5), 0.0)], CENTRE, RADIUS)
    assert len(found) == 1
    assert found[0]["closed_by"] is None


def test_leaving_takes_a_fix_past_9nm_and_8_9_is_not_enough():
    stays = visits([fix(hours(5)), fix(hours(4), at_nm(8.9), 9.0)], CENTRE, RADIUS)
    assert stays[0]["closed_by"] is None
    goes = visits([fix(hours(5)), fix(hours(4), at_nm(9.1), 9.0)], CENTRE, RADIUS)
    assert goes[0]["closed_by"] == "departure"


def test_a_fix_in_the_edge_band_does_not_start_a_visit():
    assert visits([fix(hours(4), at_nm(8.5), 0.0)], CENTRE, RADIUS) == []


def test_stopped_is_judged_by_speed_whatever_the_status_says():
    found = visits([fix(hours(2), sog=0.0, status="Under way using engine")],
                   CENTRE, RADIUS)
    assert found[0]["stopped"] is True


def test_half_a_knot_is_not_stopped():
    found = visits([fix(hours(2), sog=0.5), fix(hours(1), sog=0.6)], CENTRE, RADIUS)
    assert found[0]["stopped"] is False


def test_the_speed_sentinel_is_not_read_as_a_speed():
    found = visits([fix(hours(2), sog=102.3), fix(hours(1), sog=None)], CENTRE, RADIUS)
    assert found[0]["stopped"] is False


def test_the_arrival_window_runs_from_the_last_fix_outside_to_the_first_inside():
    ten = NOW.replace(hour=10, minute=0)
    found = visits([fix(ten, OUT, sog=9.0), fix(ten + timedelta(minutes=50))],
                   CENTRE, RADIUS)
    assert found[0]["opened_by"] == "arrival"
    assert found[0]["previous_at"] == ten
    assert found[0]["first_at"] == ten + timedelta(minutes=50)


def test_with_no_earlier_fix_the_arrival_has_no_lower_bound():
    found = visits([fix(hours(3))], CENTRE, RADIUS)
    assert found[0]["opened_by"] == "record start"
    assert found[0]["previous_at"] is None


def test_fixes_without_a_time_or_position_are_dropped_not_fatal():
    raw = [fix(hours(2)), {"observed_at": None, "lat": 2.5, "lon": 101.8, "sog": 0},
           {"observed_at": hours(1).isoformat(), "lat": None, "lon": None, "sog": 0}]
    assert len(visits(raw, CENTRE, RADIUS)[0]["fixes"]) == 1


# --- the lists (AC-5) ---------------------------------------------------------


def test_last_heard_5h_ago_with_nothing_since_is_still_at_port():
    result = board([fix(hours(8), OUT, 10.0), fix(hours(7)), fix(hours(5))])
    assert listed(result) == ["at_port"]
    row = result["at_port"][0]
    assert row["arrived_after"] == hours(8).isoformat(timespec="seconds")
    assert row["arrived_by"] == hours(7).isoformat(timespec="seconds")
    assert row["last_seen_minutes"] == 300
    assert row["hours_seen"] == 2.0


def test_last_heard_6h01_ago_with_nothing_since_has_gone_quiet_not_departed():
    result = board([fix(hours(8)), fix(hours(6, 1))])
    assert listed(result) == ["departed"]
    row = result["departed"][0]
    assert row["silent"] is True
    assert row["left_by"] is None
    assert row["left_after"] == hours(6, 1).isoformat(timespec="seconds")


def test_a_fix_outside_after_the_visit_is_a_departure_with_a_window():
    result = board([fix(hours(9)), fix(hours(4)), fix(hours(3, 30), OUT, 11.0)])
    assert listed(result) == ["departed"]
    row = result["departed"][0]
    assert row["silent"] is False
    assert row["left_after"] == hours(4).isoformat(timespec="seconds")
    assert row["left_by"] == hours(3, 30).isoformat(timespec="seconds")


def test_a_departure_47h59_ago_is_listed():
    result = board([fix(hours(50)), fix(hours(47, 59)), fix(hours(47), OUT, 11.0)])
    assert listed(result) == ["departed"]


def test_a_departure_48h01_ago_is_not():
    result = board([fix(hours(50)), fix(hours(48, 1)), fix(hours(47), OUT, 11.0)])
    assert listed(result) == []


def test_a_visit_cut_by_a_gap_is_not_a_departure_when_she_is_still_here():
    result = board([fix(hours(20)), fix(hours(3)), fix(hours(1))])
    assert listed(result) == ["at_port"]
    assert result["at_port"][0]["opened_by"] == "gap"


def test_a_ship_that_never_stopped_is_not_a_departure_even_when_bound_here():
    result = board([fix(hours(5), OUT, 12.0), fix(hours(4), IN, 9.0), fix(hours(3), OUT, 12.0)],
                   {"type": "Tanker", "destination": "MY PDI"})
    assert "departed" not in listed(result)
    # Still declaring Port Dickson and 20 nm off, so she is reported as coming.
    assert listed(result) == ["heading_in"]


# --- harbour craft (AC-6) ------------------------------------------------------


def test_a_tug_is_harbour_craft_and_a_tanker_is_not():
    assert is_harbour_craft("Tug", resident=False)
    assert not is_harbour_craft("Tanker", resident=False)


def test_residency_decides_for_an_unknown_type_at_ten_days_not_nine():
    assert residents({"a": 10, "b": 9}) == {"a"}
    assert is_harbour_craft(None, resident=True)
    assert not is_harbour_craft(None, resident=False)


def test_a_tanker_present_every_day_is_still_a_port_call():
    # GOLDEN SPLENDOR in the fixture: a tanker on all 15 dates of the window.
    assert not is_harbour_craft("Tanker", resident=True)


@pytest.mark.parametrize("vessel_type", [None, "Other", "Unknown type 10"])
def test_these_count_as_unknown(vessel_type):
    assert is_unknown_type(vessel_type)


def test_harbour_craft_never_reach_the_port_call_lists():
    tug = board([fix(hours(30)), fix(hours(29), OUT, 8.0), fix(hours(2))],
                {"type": "Tug"})
    assert listed(tug) == ["harbour_craft"]
    resident = board([fix(hours(2))], {"type": None}, days=10)
    assert listed(resident) == ["harbour_craft"]
    assert resident["harbour_craft"][0]["resident"] is True
    passer_by = board([fix(hours(2))], {"type": None}, days=9)
    assert listed(passer_by) == ["at_port"]


# --- passing through (AC-7) ----------------------------------------------------


def test_a_ship_crossing_the_circle_without_stopping_is_in_no_list():
    track = [fix(hours(3), OUT, 12.0), fix(hours(2), IN, 12.0), fix(hours(1), OUT, 12.0)]
    assert listed(board(track, {"type": "Cargo", "destination": "SGSIN"})) == []


def test_the_same_crossing_counts_when_she_declared_port_dickson():
    track = [fix(hours(3), OUT, 12.0), fix(hours(1), IN, 6.0)]
    assert listed(board(track, {"type": "Cargo", "destination": "MY PDI"})) == ["at_port"]


# --- heading in (AC-8) -----------------------------------------------------------


def test_a_ship_declaring_port_dickson_20nm_off_3h_ago_is_heading_in():
    result = board([fix(hours(3), OUT, 11.0)], {"type": "Tanker", "destination": "MY PDI"})
    assert listed(result) == ["heading_in"]
    assert round(result["heading_in"][0]["distance_nm"], 1) == 20.0


def test_heard_13h_ago_is_too_old_to_say_she_is_coming():
    result = board([fix(hours(13), OUT, 11.0)], {"type": "Tanker", "destination": "MY PDI"})
    assert listed(result) == []


def test_heard_11h59_ago_is_not():
    result = board([fix(hours(11, 59), OUT, 11.0)],
                   {"type": "Tanker", "destination": "MY PDI"})
    assert listed(result) == ["heading_in"]


def test_a_ship_that_just_left_is_not_also_heading_in():
    # SHEN HUA 801 in the fixture still declared PORT DICKSON after sailing.
    result = board([fix(hours(9)), fix(hours(4)), fix(hours(3), OUT, 12.0)],
                   {"type": "Cargo", "destination": "PORT DICKSON"})
    assert listed(result) == ["departed"]


# --- unknowns through every path (G26) ------------------------------------------


def test_a_vessel_with_no_identity_at_all_is_handled():
    result = build_board({"9": [fix(hours(1))]}, {}, {}, CENTRE, RADIUS, ALIASES, NOW)
    assert [r["mmsi"] for r in result["at_port"]] == ["9"]
    assert result["at_port"][0]["name"] is None
    assert result["at_port"][0]["destination"] is None


def test_a_vessel_with_no_usable_fixes_is_skipped():
    result = build_board({"9": [{"observed_at": None, "lat": None, "lon": None}]},
                         {}, {}, CENTRE, RADIUS, ALIASES, NOW)
    assert all(rows == [] for rows in result.values())


def test_compass_point_of_a_position_south_west_of_the_port():
    assert compass_point(CENTRE, 2.45, 101.73) == "SW"
    assert compass_point(CENTRE, 2.60, 101.80) == "N"


# --- the real capture (AC-10) ----------------------------------------------------


@pytest.fixture(scope="module")
def captured():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_board(captured):
    fields = captured["fix_fields"]
    fixes = {m: [dict(zip(fields, row)) for row in v["fixes"]]
             for m, v in captured["vessels"].items()}
    identities = {m: v["identity"] for m, v in captured["vessels"].items() if v["identity"]}
    days = {m: v["days_present_14d"] for m, v in captured["vessels"].items()}
    now = datetime.fromisoformat(captured["captured_at"])
    return build_board(fixes, identities, days, CENTRE, RADIUS, ALIASES, now)


@pytest.mark.parametrize("mmsi, name, lists", [
    ("525119160", "GOLDEN SPLENDOR", ["at_port"]),
    ("563413000", "RAINA", ["at_port"]),
    ("636015349", "MARIA PRINCESS", ["at_port"]),
    ("538009987", "DIMITRI", ["departed"]),
    ("412084000", "SHEN HUA 801", ["departed"]),
    ("533057100", "ORKIM DISCOVERY", ["departed"]),
    ("563273100", "CASTOR", ["heading_in"]),
    ("440328000", "HMM ROTTERDAM", []),
    ("563250900", "INTERASIA TRIBUTE", []),
    ("533000014", "RUBY", ["harbour_craft"]),
    ("525601509", "INDOMAL REGAL", ["harbour_craft"]),
    ("525401744", "INDOMAL DYNASTY", []),
    ("533133187", None, []),
])
def test_the_real_capture_puts_each_vessel_in_its_list(real_board, mmsi, name, lists):
    assert listed(real_board, mmsi) == lists


def test_in_the_real_capture_orkim_discovery_went_quiet_and_dimitri_sailed(real_board):
    rows = {r["mmsi"]: r for r in real_board["departed"]}
    assert rows["533057100"]["silent"] is True
    assert rows["533057100"]["left_by"] is None
    assert rows["538009987"]["silent"] is False
    assert rows["538009987"]["left_by"] is not None


def test_every_vessel_at_port_in_the_capture_was_inside_and_stopped_recently(real_board):
    for row in real_board["at_port"]:
        assert row["distance_nm"] <= RADIUS
        assert row["last_seen_minutes"] <= 6 * 60
        assert row["stopped"] is True
