"""The region table, the budget it has to fit inside, and the tools over it.

The point of this module is that a wide subscription is not free and the cost
is not visible from the shape of the request. These tests pin the two things
that make that safe to use: a rate that is never invented, and a total that
refuses to be partial.
"""

from __future__ import annotations

import pytest

from maritime_mcp_server import regions
from maritime_mcp_server.collector import Collector, DEFAULT_REGIONS
from maritime_mcp_server.store import VesselStore


# --- the table ---------------------------------------------------------------

def test_every_region_has_a_well_formed_box():
    """A malformed box is not rejected by the vendor, it closes the connection."""
    assert regions.REGIONS, "the region table is empty"
    for key, region in regions.REGIONS.items():
        assert region["box"], f"{key} has no box"
        for pair in region["box"]:
            assert len(pair) == 2, f"{key} box is not a pair of corners"
            (south, west), (north, east) = pair
            assert -90 <= south <= north <= 90, f"{key} latitudes are not south then north"
            assert -180 <= west <= 180 and -180 <= east <= 180, f"{key} longitude out of range"


def test_a_measured_region_carries_the_day_it_was_measured():
    """G15: a rate is one observation of live traffic, not a constant."""
    for key, region in regions.REGIONS.items():
        if region["rate_per_s"] is not None:
            assert region["measured_on"], f"{key} has a rate but no date"


def test_an_unmeasured_region_is_null_and_not_zero():
    """G8: zero would read as a free region, which is the opposite of unknown.

    This is the whole reason rate_for can return None, so if the table ever
    loses its unmeasured entries this test should be deleted deliberately
    rather than quietly passing on an empty loop.
    """
    unmeasured = [k for k, v in regions.REGIONS.items() if v["rate_per_s"] is None]
    assert unmeasured, "no unmeasured regions left; delete this test on purpose"
    for key in unmeasured:
        assert regions.REGIONS[key]["rate_per_s"] is None
        assert regions.REGIONS[key]["rate_per_s"] != 0


# --- normalising, which is where G19 bit before -------------------------------

@pytest.mark.parametrize("given", ["malaysia", "  Malaysia ", "MALAYSIA", "Malaysia"])
def test_a_region_key_is_normalised_the_same_way_everywhere(given):
    assert regions.parse_keys(given) == ["malaysia"]
    assert regions.boxes_for(given) == regions.REGIONS["malaysia"]["box"]
    assert regions.rate_for(given) == 0.4


def test_spaces_and_underscores_both_reach_a_hyphenated_key():
    for given in ("singapore strait", "Singapore_Strait", " SINGAPORE-STRAIT "):
        assert regions.parse_keys(given) == ["singapore-strait"]


def test_a_repeated_region_is_only_subscribed_to_once():
    """Otherwise its rate would be double counted and its box sent twice."""
    assert regions.parse_keys("malaysia,malaysia") == ["malaysia"]
    assert regions.rate_for("malaysia,malaysia") == 0.4


def test_an_unknown_key_is_reported_rather_than_silently_dropped():
    assert regions.parse_keys("malaysia,atlantis") == ["malaysia"]
    assert regions.unknown_keys("malaysia,atlantis") == ["atlantis"]


# --- the budget, which is the point ------------------------------------------

def test_a_selection_of_measured_regions_sums_its_rates():
    assert regions.rate_for("malaysia,indonesia") == pytest.approx(3.97)
    assert regions.within_budget("malaysia,indonesia") is True


def test_a_selection_over_the_budget_is_reported_as_over():
    """Mediterranean at 25.1 plus US East at 10.1 is past what held a connection."""
    assert regions.rate_for("mediterranean,us-east") == pytest.approx(35.2)
    assert regions.within_budget("mediterranean,us-east") is False


def test_a_selection_containing_an_unmeasured_region_has_an_unknown_total():
    """The failure this prevents: a partial sum is lowest exactly when the
    unmeasured region is busiest, so it would read as safe when it is not."""
    unmeasured = next(k for k, v in regions.REGIONS.items() if v["rate_per_s"] is None)
    assert regions.rate_for(f"malaysia,{unmeasured}") is None
    assert regions.within_budget(f"malaysia,{unmeasured}") is None
    assert regions.unmeasured(f"malaysia,{unmeasured}") == [unmeasured]


def test_describe_reports_the_budget_and_the_evidence_for_it():
    described = regions.describe("malaysia")
    assert described["budget_per_s"] == regions.STABLE_BUDGET_PER_S
    assert "152s" in described["budget_basis"], "the basis should cite what was observed"
    assert described["selected_rate_per_s"] == 0.4
    assert described["within_budget"] is True
    assert all("box" not in r for r in described["regions"]), "wire format should not leak"
    assert all("bounds" in r for r in described["regions"])


# --- geometry ----------------------------------------------------------------

def test_bounds_are_the_outer_extent_of_the_boxes():
    assert regions.bounds_of([[[0.5, 98.5], [7.5, 119.5]]]) == {
        "south": 0.5, "west": 98.5, "north": 7.5, "east": 119.5}


def test_contains_answers_for_a_real_position():
    # Port Klang is inside Malaysia and nowhere near the Mediterranean.
    assert regions.contains("malaysia", 3.00, 101.36) is True
    assert regions.contains("mediterranean", 3.00, 101.36) is False


def test_contains_is_false_rather_than_raising_for_a_missing_position():
    assert regions.contains("malaysia", None, None) is False
    assert regions.contains("atlantis", 3.0, 101.0) is False


# --- the collector's selection ------------------------------------------------

def test_an_unconfigured_collector_still_watches_malaysia():
    """S09's coverage guarantee has to survive the subscription becoming a choice."""
    c = Collector(VesselStore(), api_key="x")
    assert c.regions == list(DEFAULT_REGIONS) == ["malaysia"]


def test_the_environment_can_select_regions(monkeypatch):
    monkeypatch.setenv("MARITIME_MCP_REGIONS", " Malaysia , indonesia ")
    c = Collector(VesselStore(), api_key="x")
    assert c.regions == ["malaysia", "indonesia"]
    assert len(c._boxes()) == 2


def test_an_environment_naming_only_nonsense_falls_back_rather_than_subscribing_to_nothing(monkeypatch):
    """An empty BoundingBoxes list fails the handshake every time, with an error
    that says nothing about the typo that caused it."""
    monkeypatch.setenv("MARITIME_MCP_REGIONS", "atlantis,narnia")
    c = Collector(VesselStore(), api_key="x")
    assert c.regions == ["malaysia"]
    assert c._boxes()


def test_an_explicit_box_still_wins_over_regions():
    """Existing callers and tests pass boxes directly and must not be re-pointed."""
    box = [[[1.0, 2.0], [3.0, 4.0]]]
    c = Collector(VesselStore(), api_key="x", bounding_boxes=box)
    assert c._boxes() == box


@pytest.mark.anyio
async def test_set_regions_changes_the_selection_and_reports_the_cost():
    c = Collector(VesselStore(), api_key="x")
    result = await c.set_regions("indonesia,us-east")
    assert result["ok"] is True
    assert result["regions"] == ["indonesia", "us-east"]
    assert result["estimated_rate_per_s"] == pytest.approx(13.67)
    assert result["within_budget"] is True
    # No socket open, so it cannot have been applied in place.
    assert result["applied_immediately"] is False
    assert c.regions == ["indonesia", "us-east"]


@pytest.mark.anyio
async def test_set_regions_refuses_a_selection_it_cannot_understand():
    c = Collector(VesselStore(), api_key="x")
    result = await c.set_regions("atlantis")
    assert result["ok"] is False
    assert result["unknown"] == ["atlantis"]
    # The old selection survives a refused change.
    assert c.regions == ["malaysia"]


@pytest.mark.anyio
async def test_an_over_budget_selection_is_allowed_and_flagged():
    """The feed is the user's to spend. The honest answer is the cost, not a
    refusal invented by this server."""
    c = Collector(VesselStore(), api_key="x")
    result = await c.set_regions("mediterranean,us-east")
    assert result["ok"] is True
    assert result["within_budget"] is False
    assert c.regions == ["mediterranean", "us-east"]
