"""Hourly activity counts: how busy an area has been.

The number this exists to produce is "how many ships are queued at anchor",
which a charterer rings an agent about. Everything here is about counting that
honestly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server.history import VesselHistory

START = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
BOX = (1.0, 103.5, 1.6, 104.2)      # south, west, north, east


@pytest.fixture
def history(tmp_path):
    h = VesselHistory(path=str(tmp_path / "v.db"))
    yield h
    h.close()


def record(h, mmsi, minutes, status, lat=1.26, lon=103.82, sog=0.0):
    h.record_position(mmsi, START + timedelta(minutes=minutes), lat, lon, sog, status)


def test_a_vessel_reporting_many_times_in_an_hour_counts_once(history):
    """A moored vessel reports every three minutes. Counting rows would say
    twenty ships where there is one."""
    for minute in range(0, 60, 3):
        record(history, "1", minute, "At anchor")
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert len(hours) == 1
    assert hours[0]["at_anchor"] == 1
    assert hours[0]["positions"] == 20


def test_vessels_are_split_by_what_they_reported(history):
    record(history, "1", 5, "At anchor")
    record(history, "2", 5, "At anchor")
    record(history, "3", 5, "Moored")
    record(history, "4", 5, "Under way using engine", sog=12.0)
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert hours[0]["at_anchor"] == 2
    assert hours[0]["moored"] == 1
    assert hours[0]["under_way"] == 1
    assert hours[0]["vessels"] == 4


def test_positions_outside_the_box_are_not_counted(history):
    record(history, "1", 5, "At anchor")
    record(history, "2", 5, "At anchor", lat=3.0, lon=101.4)     # Port Klang
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert hours[0]["at_anchor"] == 1


def test_each_hour_is_reported_separately(history):
    record(history, "1", 5, "At anchor")
    record(history, "2", 65, "At anchor")
    record(history, "3", 70, "At anchor")
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert [h["at_anchor"] for h in hours] == [1, 2]


def test_an_hour_with_no_coverage_is_simply_absent(history):
    """It cannot be told apart from an hour with no ships, which is why the
    caller is given the position count alongside every number."""
    record(history, "1", 5, "At anchor")
    record(history, "2", 185, "At anchor")          # two hours later
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert len(hours) == 2, "the empty hour should not be invented as a zero row"
    assert all(h["positions"] > 0 for h in hours)


def test_a_vessel_counts_in_every_hour_it_was_heard_in(history):
    record(history, "1", 5, "At anchor")
    record(history, "1", 65, "At anchor")
    hours = history.activity_by_hour(START - timedelta(hours=1), *BOX)
    assert [h["at_anchor"] for h in hours] == [1, 1]
