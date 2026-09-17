"""Port call reconstruction.

The value of this module is entirely in what it refuses to claim, so most of
these tests are about restraint rather than detection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server import port_calls
from maritime_mcp_server.port_calls import find_calls, summarise

START = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
BERTH = (1.264, 103.822)


def at_singapore(lat, lon):
    """A nearest_port that puts the berth at Singapore and everything far from
    it at sea, so the tests exercise the distance rule without a port table."""
    import math
    dlat = abs(lat - BERTH[0]) * 60
    dlon = abs(lon - BERTH[1]) * 60 * math.cos(math.radians(lat))
    return "Singapore", math.hypot(dlat, dlon)


#: A moored or anchored Class A vessel reports every few minutes, so a realistic
#: track is dense. Writing the tests with fixes hours apart would have every
#: stop cut by the coverage-gap rule, which is the rule working rather than a
#: fault, but it would test nothing.
REPORT_EVERY = timedelta(minutes=10)


def track(*steps):
    """Build a dense track from sparse instructions.

    steps are (minutes_from_start, sog, status) and optionally (lat, lon). Each
    step holds until the next one, with a fix emitted every REPORT_EVERY, which
    is what a real vessel transmits.
    """
    out = []
    for index, (minutes, sog, status, *rest) in enumerate(steps):
        lat, lon = rest[0] if rest else BERTH
        start = START + timedelta(minutes=minutes)
        end = (START + timedelta(minutes=steps[index + 1][0])
               if index + 1 < len(steps) else start)
        moment = start
        if index + 1 == len(steps):
            out.append({"observed_at": start, "lat": lat, "lon": lon,
                        "sog": sog, "status": status})
            continue
        # Up to but not including the next step, which emits its own first fix.
        # Emitting the boundary twice put a stopped and a moving fix at the same
        # instant and quietly extended every stop by one reporting interval.
        while moment < end:
            out.append({"observed_at": moment, "lat": lat, "lon": lon,
                        "sog": sog, "status": status})
            moment += REPORT_EVERY
    return out


def gap(minutes_from_start, sog, status):
    """A single fix with nothing around it, for testing coverage holes."""
    return [{"observed_at": START + timedelta(minutes=minutes_from_start),
             "lat": BERTH[0], "lon": BERTH[1], "sog": sog, "status": status}]


# --- the happy case ----------------------------------------------------------

def test_a_complete_call_has_an_arrival_and_a_departure():
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Moored"),
        (300, 0.0, "Moored"),
        (310, 7.0, "Under way using engine"),
    ), at_singapore)
    assert len(calls) == 1
    call = calls[0]
    assert call["port"] == "Singapore"
    assert call["arrived_at"].startswith("2026-09-17T00:10")
    assert call["departed_at"].startswith("2026-09-17T05:10")
    assert call["hours"] == pytest.approx(4.8, abs=0.1)
    assert call["still_there"] is False
    assert call["arrival_observed"] is True
    assert call["status"] == "Moored"


# --- restraint ---------------------------------------------------------------

def test_a_vessel_still_alongside_is_not_given_a_departure_time():
    """Inventing one would put a fabricated time into a laytime argument."""
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Moored"),
        (200, 0.0, "Moored"),
    ), at_singapore)
    assert len(calls) == 1
    assert calls[0]["departed_at"] is None
    assert calls[0]["still_there"] is True


def test_a_stop_is_cut_at_a_hole_in_coverage_rather_than_spanned():
    """Twelve hours of silence is not evidence that she sat there for twelve
    hours. It is evidence of nothing."""
    before = track((0, 8.0, "Under way using engine"), (10, 0.0, "Moored"),
                   (100, 0.0, "Moored"))
    after = track((820, 0.0, "Moored"), (900, 0.0, "Moored"))   # 12 hours later
    calls = find_calls(before + after, at_singapore)
    assert len(calls) == 2, "the gap should have split this into two stops"
    assert calls[0]["departed_at"] is None
    assert calls[0]["hours"] == pytest.approx(1.5, abs=0.1)
    assert calls[1]["arrival_observed"] is False


def test_an_arrival_is_not_claimed_when_the_record_starts_mid_stop():
    """Otherwise the arrival time is just when this server started listening."""
    calls = find_calls(track(
        (0, 0.0, "Moored"),
        (300, 0.0, "Moored"),
        (310, 7.0, "Under way using engine"),
    ), at_singapore)
    assert calls[0]["arrival_observed"] is False
    assert calls[0]["departed_at"] is not None


def test_a_brief_stop_is_not_a_call():
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Under way using engine"),
        (30, 0.0, "Under way using engine"),
        (40, 8.0, "Under way using engine"),
    ), at_singapore)
    assert calls == []


def test_a_stop_far_from_any_port_is_reported_as_at_sea():
    far = (3.5, 99.0)
    calls = find_calls(track(
        (0, 8.0, "Under way using engine", far),
        (10, 0.0, "At anchor", far),
        (300, 0.0, "At anchor", far),
        (310, 8.0, "Under way using engine", far),
    ), at_singapore)
    assert len(calls) == 1
    assert calls[0]["at_sea"] is True
    assert calls[0]["port"] is None, "a distant stop must not borrow a port's name"


def test_the_speed_sentinel_does_not_end_a_stop():
    """1023 scaled is 102.3 knots and means "not available". Read as a speed it
    is well over the moving threshold and would close every stop it touched."""
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Moored"),
        (100, 102.3, "Moored"),
        (300, 0.0, "Moored"),
        (310, 7.0, "Under way using engine"),
    ), at_singapore)
    assert len(calls) == 1, "the sentinel was read as movement"
    assert calls[0]["hours"] == pytest.approx(4.8, abs=0.1)


def test_creeping_between_the_thresholds_does_not_manufacture_a_call():
    """One knot is neither stopped nor under way. Flipping on it would split one
    call into several."""
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Moored"),
        (100, 1.2, "Moored"),
        (200, 0.0, "Moored"),
        (300, 0.0, "Moored"),
        (310, 7.0, "Under way using engine"),
    ), at_singapore)
    assert len(calls) == 1


def test_a_stray_status_does_not_relabel_the_whole_stop():
    """Mode, not last value: the engines coming on at the end should not turn
    eleven hours at anchor into eleven hours under way."""
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "At anchor"),
        (100, 0.0, "At anchor"),
        (200, 0.0, "At anchor"),
        (300, 0.0, "Under way using engine"),
        (310, 7.0, "Under way using engine"),
    ), at_singapore)
    assert calls[0]["status"] == "At anchor"


def test_fixes_arriving_out_of_order_are_sorted_first():
    calls = find_calls(list(reversed(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Moored"),
        (300, 0.0, "Moored"),
        (310, 7.0, "Under way using engine"),
    ))), at_singapore)
    assert len(calls) == 1
    assert calls[0]["arrived_at"].startswith("2026-09-17T00:10")


def test_a_fix_without_a_position_is_ignored_rather_than_crashing():
    fixes = track((0, 8.0, "Under way"), (10, 0.0, "Moored"), (300, 0.0, "Moored"))
    fixes.append({"observed_at": START, "lat": None, "lon": None, "sog": 0, "status": None})
    assert find_calls(fixes, at_singapore)


# --- the summary a laytime conversation starts from --------------------------

def test_the_summary_keeps_waiting_and_working_apart():
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "At anchor"),
        (610, 0.0, "At anchor"),
        (620, 6.0, "Under way using engine"),
        (700, 0.0, "Moored"),
        (1000, 0.0, "Moored"),
        (1010, 6.0, "Under way using engine"),
    ), at_singapore)
    assert len(calls) == 2
    totals = summarise(calls)
    assert totals["calls"] == 2
    assert totals["hours_at_anchor"] == pytest.approx(10.0, abs=0.2)
    assert totals["hours_alongside"] == pytest.approx(5.0, abs=0.2)
    assert totals["still_there"] is False


def test_the_summary_parts_add_up_to_the_whole():
    """A stopped vessel often reports "Under way using engine", which is honest
    AIS for a tug holding station with her engines on. Counting only moored and
    anchored reported calls with no hours against them: seven calls, zero hours.
    Observed on production data, where every displayed call had that status."""
    calls = find_calls(track(
        (0, 8.0, "Under way using engine"),
        (10, 0.0, "Under way using engine"),
        (190, 0.0, "Under way using engine"),
        (200, 6.0, "Under way using engine"),
    ), at_singapore)
    assert len(calls) == 1
    totals = summarise(calls)
    assert totals["hours_alongside"] == 0
    assert totals["hours_at_anchor"] == 0
    assert totals["hours_otherwise_stopped"] == pytest.approx(3.0, abs=0.2)
    assert totals["hours_total"] == pytest.approx(
        totals["hours_alongside"] + totals["hours_at_anchor"]
        + totals["hours_otherwise_stopped"], abs=0.1)
