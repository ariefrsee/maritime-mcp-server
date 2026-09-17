"""Finding anchorages in the positions.

The whole thing is a clustering decision, so the tests are about where it draws
the line: what counts as one place, what counts as none, and what it refuses to
claim.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maritime_mcp_server.anchorages import (
    MIN_VESSELS,
    bounds_nm2,
    cluster,
    footprint_nm2,
)
from maritime_mcp_server.history import VesselHistory

CELL = 0.01
START = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
BOX = (1.0, 103.5, 1.6, 104.2)


def cells(*entries):
    """(lat, lon, vessels, positions) as the history layer returns them."""
    return [(lat, lon, vessels, vessels * 10) for lat, lon, vessels in entries]


# --- what counts as one place -------------------------------------------------

def test_touching_cells_become_one_anchorage():
    out = cluster(cells((1.25, 103.80, 5), (1.26, 103.80, 7), (1.26, 103.81, 4)), CELL)
    assert len(out) == 1
    assert out[0]["vessels"] == 16
    assert out[0]["cells"] == 3


def test_cells_that_touch_only_diagonally_are_still_one_place():
    out = cluster(cells((1.25, 103.80, 4), (1.26, 103.81, 4)), CELL)
    assert len(out) == 1


def test_a_single_empty_cell_does_not_split_an_anchorage():
    """Reach is one cell of slack, so a hole in the middle of a busy anchorage
    does not report it as two."""
    out = cluster(cells((1.25, 103.80, 5), (1.27, 103.80, 5)), CELL)
    assert len(out) == 1, "a one cell hole should not split it"


def test_distant_cells_are_separate_anchorages():
    out = cluster(cells((1.25, 103.80, 5), (3.00, 101.36, 9)), CELL)
    assert len(out) == 2


# --- what it refuses to claim -------------------------------------------------

def test_too_few_vessels_is_not_an_anchorage():
    """One yacht swinging on a mooring for a week is not a queue, and without a
    floor every quiet bay in the region becomes a labelled place.

    Written with literals rather than against MIN_VESSELS. The first version
    used MIN_VESSELS - 1, which meant lowering the constant to 1 tested zero
    vessels and passed on an empty case, so the floor could have been removed
    entirely without a single test noticing.
    """
    assert MIN_VESSELS == 3, "the numbers below are chosen against this floor"
    assert cluster(cells((1.25, 103.80, 1)), CELL) == []
    assert cluster(cells((1.25, 103.80, 2)), CELL) == []
    assert len(cluster(cells((1.25, 103.80, 3)), CELL)) == 1


def test_a_long_stay_does_not_inflate_the_count():
    """Counts are distinct vessels. Positions would make one ship anchored for a
    week look like a hundred ships."""
    few_ships_many_reports = [(1.25, 103.80, 3, 5000)]
    out = cluster(few_ships_many_reports, CELL)
    assert out[0]["vessels"] == 3
    assert out[0]["positions"] == 5000


def test_nothing_is_given_a_name():
    out = cluster(cells((1.25, 103.80, 9)), CELL)
    assert "name" not in out[0], "AIS does not say what an anchorage is called"


# --- the shape it reports -----------------------------------------------------

def test_the_extent_covers_every_cell_rather_than_a_fitted_circle():
    """An anchorage is usually long and thin along a coast. A radius would claim
    water nobody anchors in."""
    out = cluster(cells((1.25, 103.80, 4), (1.25, 103.90, 4), (1.25, 104.00, 4)), CELL)
    assert len(out) == 3, "these are far enough apart to be separate"
    wide = cluster(cells((1.25, 103.80, 4), (1.25, 103.81, 4), (1.25, 103.82, 4)), CELL)[0]
    assert wide["west"] < 103.80 and wide["east"] > 103.82
    assert wide["north"] - wide["south"] < wide["east"] - wide["west"], "long and thin"


def test_the_centre_sits_where_the_ships_are():
    """Weighted by vessels, not the middle of the bounding box: an anchorage
    with one busy end and one empty end should point at the busy end."""
    out = cluster(cells((1.25, 103.80, 1), (1.26, 103.80, 1), (1.27, 103.80, 40)), CELL)
    assert len(out) == 1
    assert out[0]["lat"] > 1.265, f"centre pulled to the crowded end, got {out[0]['lat']}"


def test_biggest_anchorage_comes_first():
    out = cluster(cells((1.25, 103.80, 4), (3.00, 101.36, 40)), CELL)
    assert out[0]["vessels"] == 40


def test_the_footprint_is_the_cells_occupied_not_the_box_around_them():
    """The first version reported the bounding box. At Singapore that was 226
    square miles against 64 actually occupied: the box reached from Jurong to
    Batam and took in the island, Sentosa and the main fairway. Drawing it made
    the map claim all of that as anchorage."""
    # An L shape: three cells occupied, but the box around them covers four.
    out = cluster(cells((1.25, 103.80, 4), (1.26, 103.80, 4), (1.25, 103.81, 4)), CELL)[0]
    assert out["cells"] == 3
    assert footprint_nm2(out, CELL) < bounds_nm2(out), "the box must be the larger number"
    assert footprint_nm2(out, CELL) == pytest.approx(bounds_nm2(out) * 3 / 4, rel=0.1)


def test_the_occupied_cells_are_returned_so_the_shape_can_be_drawn():
    out = cluster(cells((1.25, 103.80, 4), (1.26, 103.80, 4)), CELL)[0]
    assert len(out["footprint"]) == 2
    assert [1.25, 103.8] in out["footprint"]
    assert [1.26, 103.8] in out["footprint"]


# --- against the real query ---------------------------------------------------

@pytest.fixture
def history(tmp_path):
    h = VesselHistory(path=str(tmp_path / "v.db"))
    yield h
    h.close()


def test_only_anchored_vessels_are_counted(history):
    """The layer is about waiting. A ship steaming through the same water is
    not part of the queue."""
    for n in range(5):
        history.record_position(f"anchored{n}", START, 1.25, 103.80, 0.0, "At anchor")
    for n in range(20):
        history.record_position(f"passing{n}", START, 1.25, 103.80, 12.0, "Under way using engine")

    grid = history.density(START - timedelta(days=1), *BOX, CELL, status="At anchor")
    found = cluster(grid, CELL)
    assert len(found) == 1
    assert found[0]["vessels"] == 5, "the twenty passing ships should not be in the queue"
