"""The particulars AIS transmits and this server used to discard.

Every one of these fields has a sentinel that means "not reported", and every
one of those sentinels is a plausible-looking number. That is what the tests
are about.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maritime_mcp_server import ais_mapping

CAPTURE = Path(__file__).parent / "data" / "ais_capture.json"


@pytest.fixture(scope="module")
def statics():
    msgs = json.loads(CAPTURE.read_text())
    return [m["Message"]["ShipStaticData"] for m in msgs
            if m.get("MessageType") == "ShipStaticData"]


# --- IMO -----------------------------------------------------------------

def test_a_malformed_imo_is_rejected():
    assert ais_mapping.imo_number(9999999) is None
    assert ais_mapping.imo_number(123) is None
    assert ais_mapping.imo_number("9386110") is None
    assert ais_mapping.imo_number(None) is None


def test_a_real_imo_is_accepted():
    assert ais_mapping.imo_number(9386110) == 9386110
    assert ais_mapping.imo_number(9258686) == 9258686


def test_the_checksum_is_not_proof_of_registration():
    """This is the honest limit of the check and it is worth pinning, because
    the temptation is to present a checksum pass as a verified identity.

    1149346 comes from a small craft called STL PT6 in real Malaysian traffic
    and passes: weighted sum 86, last digit 6, check digit 6. So does 1234567.
    A random seven digit number passes one time in ten.
    """
    assert ais_mapping.imo_number(1149346) == 1149346
    assert ais_mapping.imo_number(1234567) == 1234567


# --- draught, beam ---------------------------------------------------------

def test_zero_draught_is_not_a_vessel_drawing_nothing():
    assert ais_mapping.draught_m(0) is None
    assert ais_mapping.draught_m(11.5) == 11.5


def test_beam_comes_from_the_port_and_starboard_offsets():
    assert ais_mapping.beam_from_dimension({"A": 147, "B": 37, "C": 22, "D": 10}) == 32
    assert ais_mapping.beam_from_dimension({"A": 0, "B": 0, "C": 0, "D": 0}) is None
    assert ais_mapping.beam_from_dimension(None) is None


# --- ETA -------------------------------------------------------------------

def test_an_unset_eta_is_absent_not_a_date():
    """Month 0, day 0, hour 24 and minute 60 all mean nobody filled it in."""
    assert ais_mapping.declared_eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}) is None
    assert ais_mapping.declared_eta({"Month": 9, "Day": 0, "Hour": 12, "Minute": 0}) is None
    assert ais_mapping.declared_eta({"Month": 9, "Day": 13, "Hour": 24, "Minute": 0}) is None


def test_a_set_eta_keeps_its_own_shape():
    """Not a timestamp. AIS sends no year and no timezone, so building a
    datetime means inventing a year and asserting a zone nobody sent."""
    eta = ais_mapping.declared_eta({"Month": 9, "Day": 13, "Hour": 22, "Minute": 0})
    assert eta == "13-09 22:00"
    assert "2026" not in eta


# --- rate of turn ----------------------------------------------------------

def test_rate_of_turn_sentinel_is_not_a_hard_turn():
    """-128 is "no sensor". Read raw it is the largest magnitude in the field."""
    assert ais_mapping.rate_of_turn(-128) is None
    assert ais_mapping.rate_of_turn(None) is None


def test_rate_of_turn_is_decoded_not_passed_through():
    """It is sent as a signed square root scaled by 4.733, so 3 is not 3."""
    turn = ais_mapping.rate_of_turn(3)
    assert turn["degrees_per_minute"] == pytest.approx(0.4, abs=0.05)
    assert turn["off_scale"] is False


def test_the_direction_of_the_turn_survives():
    assert ais_mapping.rate_of_turn(-10)["degrees_per_minute"] < 0
    assert ais_mapping.rate_of_turn(10)["degrees_per_minute"] > 0


def test_off_scale_says_so_rather_than_inventing_precision():
    turn = ais_mapping.rate_of_turn(127)
    assert turn["off_scale"] is True
    assert turn["degrees_per_minute"] == 708.0


# --- against the real capture -----------------------------------------------

def test_the_captured_traffic_yields_particulars(statics):
    parsed = [ais_mapping.static_fields(b) for b in statics]
    assert sum(1 for p in parsed if p["imo"]) >= 10, "IMO should come through"
    assert sum(1 for p in parsed if p["draught_m"]) >= 10, "draught should come through"
    assert sum(1 for p in parsed if p["call_sign"]) >= 10, "call sign should come through"
    assert sum(1 for p in parsed if p["beam_m"]) >= 10, "beam should come through"
    # Most vessels in the capture never set an ETA, which is the normal case.
    assert any(p["eta_declared"] for p in parsed), "at least one ETA was set"


# The record-shape tests are satisfied by a key existing, and every one of these
# keys already existed as a None in to_record's base dict. That is how S25
# shipped position_fields without the turn wired in at all and still went green.
# These assert a value arriving from a real message body, not a key.
def test_turn_and_accuracy_reach_the_record_from_a_position_body():
    rec = ais_mapping.to_record(
        position={"Latitude": 1.25, "Longitude": 103.8, "Sog": 12.0,
                  "RateOfTurn": 20, "PositionAccuracy": True},
        mmsi="563186500")
    assert rec["rate_of_turn_dpm"] == round((20 / 4.733) ** 2, 1)
    assert rec["turn_off_scale"] is False
    assert rec["position_accurate"] is True


def test_a_steady_helm_is_zero_not_missing():
    """RateOfTurn 0 is the commonest value in the feed and it is a measurement.

    Treating it as falsy anywhere in the chain would drop the turn field on
    most of the fleet, which is the majority case, not an edge case.
    """
    rec = ais_mapping.to_record(position={"Latitude": 1.0, "Longitude": 103.0,
                                "RateOfTurn": 0}, mmsi="563186500")
    assert rec["rate_of_turn_dpm"] == 0.0
    assert rec["turn_off_scale"] is False
