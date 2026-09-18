"""Observed passage times.

Everything here is about what the module refuses to claim. The number is easy;
not overstating it is the work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server.passages import MIN_OBSERVATIONS, passages_for, summarise

START = datetime(2026, 9, 17, tzinfo=timezone.utc)
SINGAPORE = (1.264, 103.822)
PORT_DICKSON = (2.523, 101.796)
MIDWAY = (2.0, 102.6)


def fix(hours, lat, lon):
    return {"observed_at": START + timedelta(hours=hours), "lat": lat, "lon": lon}


def leg(depart_after=0, arrive_at=14):
    """Sits off Singapore, then steams to Port Dickson."""
    return (
        [fix(h, *SINGAPORE) for h in range(0, depart_after + 1)]
        + [fix((depart_after + arrive_at) / 2, *MIDWAY), fix(arrive_at, *PORT_DICKSON)]
    )


def test_a_completed_passage_is_found():
    found = passages_for(leg(0, 14), SINGAPORE, PORT_DICKSON)
    assert len(found) == 1
    assert found[0]["hours"] == 14.0


def test_time_spent_waiting_at_the_origin_is_not_passage_time():
    """A ship anchored off the port for six hours did not spend them steaming.
    The clock starts at the last fix near the origin, not the first."""
    found = passages_for(leg(depart_after=6, arrive_at=20), SINGAPORE, PORT_DICKSON)
    assert len(found) == 1
    assert found[0]["hours"] == 14.0, "the six hours at anchor were counted as passage"


def test_arriving_without_having_departed_is_not_a_passage():
    """The record starting mid-voyage is not evidence of a voyage."""
    arrival_only = [fix(2, *MIDWAY), fix(6, *PORT_DICKSON)]
    assert passages_for(arrival_only, SINGAPORE, PORT_DICKSON) == []


def test_a_passage_longer_than_the_cap_is_discarded():
    """She called somewhere in between. Averaging that in makes the leg look
    worse for everyone who did not."""
    slow = [fix(0, *SINGAPORE), fix(24 * 20, *PORT_DICKSON)]
    assert passages_for(slow, SINGAPORE, PORT_DICKSON) == []


def test_the_other_direction_is_not_counted():
    back = [fix(0, *PORT_DICKSON), fix(8, *MIDWAY), fix(14, *SINGAPORE)]
    assert passages_for(back, SINGAPORE, PORT_DICKSON) == []
    assert len(passages_for(back, PORT_DICKSON, SINGAPORE)) == 1


def test_two_separate_round_trips_are_two_passages():
    track = leg(0, 14) + [fix(20, *SINGAPORE), fix(26, *MIDWAY), fix(34, *PORT_DICKSON)]
    assert len(passages_for(track, SINGAPORE, PORT_DICKSON)) == 2


def test_fixes_out_of_order_are_sorted_first():
    assert len(passages_for(list(reversed(leg(0, 14))), SINGAPORE, PORT_DICKSON)) == 1


# --- the summary, which is where a number gets overstated ---------------------

def test_too_few_passages_gets_no_median():
    """A median of two numbers is a coincidence, not a benchmark, and someone
    will build a schedule on whatever is printed."""
    assert MIN_OBSERVATIONS == 5, "the counts below are chosen against this floor"
    for n in (1, 2, 4):
        out = summarise([{"hours": 14.0}] * n)
        assert out["enough"] is False
        assert "median_hours" not in out
    assert summarise([{"hours": 14.0}] * 5)["enough"] is True


def test_the_spread_is_always_given_with_the_middle():
    """A leg with a median of 14 and a range of 7 to 62 is not a leg anyone
    should schedule to 14."""
    hours = [7.5, 11.0, 14.0, 22.0, 62.5]
    out = summarise([{"hours": h} for h in hours])
    assert out["median_hours"] == 14.0
    assert out["fastest_hours"] == 7.5
    assert out["slowest_hours"] == 62.5
    assert out["p25_hours"] <= out["median_hours"] <= out["p75_hours"]


def test_implied_speed_is_over_the_whole_leg_including_stops():
    out = summarise([{"hours": 14.0}] * 5, distance_nm=180)
    assert out["median_speed_kn"] == pytest.approx(12.9, abs=0.1)


# --- against the server's own port table --------------------------------------

def test_the_port_table_the_tool_reads_actually_exists():
    """The first version referenced PORTS, which is not what the table is
    called, so the tool raised a NameError on every single invocation and the
    error surfaced only as "Error executing tool"."""
    from maritime_mcp_server import server

    assert hasattr(server, "PORT_COORDS")
    assert not hasattr(server, "PORTS")
    for name in ("singapore", "port klang", "port dickson", "tanjung pelepas"):
        assert name in server.PORT_COORDS, f"{name} missing from the port table"


def test_singapore_is_the_nearest_port_to_a_ship_in_singapore():
    """It was absent from the table, so a vessel in the roads was reported as
    being a dozen miles from Pasir Gudang across a border. True, and no use."""
    from maritime_mcp_server.server import _nearest_port

    port, distance = _nearest_port(1.264, 103.822)
    assert port == "Singapore"
    assert distance < 1
