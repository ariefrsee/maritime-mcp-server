"""Traffic density: recorded positions collapsed onto a grid.

The point that needs guarding is that vessels and positions are counted
separately. One ship anchored for two days makes hundreds of reports in a
single cell, and a density map that counts reports says that berth is the
busiest water in the strait.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server.history import VesselHistory

START = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
BOX = (1.0, 103.5, 1.6, 104.2)      # south, west, north, east
CELL = 0.02


@pytest.fixture
def history(tmp_path):
    h = VesselHistory(path=str(tmp_path / "v.db"))
    yield h
    h.close()


def put(h, mmsi, minutes, lat, lon):
    h.record_position(mmsi, START + timedelta(minutes=minutes), lat, lon, 0.0, "At anchor")


def cells(h):
    return {(c[0], c[1]): (c[2], c[3])
            for c in h.density(START - timedelta(days=1), *BOX, CELL)}


def test_positions_in_the_same_cell_are_collapsed(history):
    put(history, "1", 0, 1.261, 103.821)
    put(history, "1", 5, 1.262, 103.822)
    put(history, "1", 10, 1.263, 103.823)
    grid = cells(history)
    assert len(grid) == 1
    vessels, positions = next(iter(grid.values()))
    assert vessels == 1
    assert positions == 3


def test_one_ship_reporting_often_does_not_outweigh_many_ships(history):
    """A berth with one moored vessel would otherwise dominate the lane."""
    for minute in range(0, 300, 3):                 # one ship, 100 reports
        put(history, "moored", minute, 1.261, 103.821)
    for n in range(20):                             # twenty ships, once each
        put(history, f"passing{n}", n, 1.401, 103.901)
    grid = cells(history)
    berth = grid[(round(1.26, 5), round(103.82, 5))]
    lane = grid[(round(1.4, 5), round(103.9, 5))]
    assert berth == (1, 100)
    assert lane == (20, 20)
    assert lane[0] > berth[0], "by vessels, the lane is busier"
    assert berth[1] > lane[1], "by reports, the berth looks busier, which is the trap"


def test_cells_outside_the_box_are_excluded(history):
    put(history, "1", 0, 1.261, 103.821)
    put(history, "2", 0, 3.000, 101.360)            # Port Klang, outside
    assert len(cells(history)) == 1


def test_a_finer_cell_splits_what_a_coarse_one_merges(history):
    # Deliberately close together: two points a few hundred metres apart share a
    # 0.05 degree cell and occupy different 0.005 degree ones. Picking them
    # further apart tests nothing, because they straddle a boundary at both.
    put(history, "1", 0, 1.261, 103.821)
    put(history, "2", 0, 1.263, 103.823)
    coarse = history.density(START - timedelta(days=1), *BOX, 0.05)
    fine = history.density(START - timedelta(days=1), *BOX, 0.005)
    assert len(coarse) == 1
    assert len(fine) == 2


def test_positions_before_the_window_are_excluded(history):
    put(history, "old", -60 * 48, 1.261, 103.821)
    put(history, "new", 0, 1.261, 103.821)
    grid = history.density(START - timedelta(hours=1), *BOX, CELL)
    assert len(grid) == 1
    assert grid[0][2] == 1, "only the vessel inside the window should count"
