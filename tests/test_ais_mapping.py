"""The pure translation layer: AIS wire fields into this project's record shape.

Every case here traces to a guardrail or to something a retro found, not to a
reading of the implementation. Per G11, each one asserts a value rather than a
shape, a type or a truthiness.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from maritime_mcp_server import ais_mapping as m


# --- navigational status -----------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    (0, "Under way using engine"),
    (1, "At anchor"),
    (5, "Moored"),
    (7, "Engaged in fishing"),
    (8, "Under way sailing"),
    (15, "Undefined"),
])
def test_known_status_codes_map_to_their_words(code, expected):
    assert m.navigational_status(code) == expected


def test_every_status_0_to_15_is_covered():
    """The live capture contained 0, 1, 3, 5, 8 and 15. The table must be whole."""
    words = [m.navigational_status(c) for c in range(16)]
    assert all(w and not w.startswith("Unknown") for w in words)
    assert len(set(words)) >= 14, "codes should not collapse onto one label"


def test_unknown_status_reports_itself_rather_than_guessing():
    """G8: an unrecognised code is never mapped to the nearest known value."""
    assert m.navigational_status(99) == "Unknown status 99"


def test_absent_status_stays_absent():
    """Class B transponders send no status. Defaulting it would be a fabrication."""
    assert m.navigational_status(None) is None


# --- ship type ---------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    (70, "Cargo"), (71, "Cargo"), (79, "Cargo"),
    (80, "Tanker"), (86, "Tanker"), (89, "Tanker"),
    (60, "Passenger"), (90, "Other"), (99, "Other"),
])
def test_ship_type_maps_by_decade(code, expected):
    assert m.ship_type(code) == expected


@pytest.mark.parametrize("code,expected", [
    (30, "Fishing"), (31, "Tug"), (33, "Dredger"),
    (36, "Sailing vessel"), (50, "Pilot vessel"), (52, "Tug"),
])
def test_specific_type_codes_override_their_decade(code, expected):
    assert m.ship_type(code) == expected


def test_unknown_type_reports_itself():
    assert m.ship_type(123) == "Unknown type 123"


def test_absent_type_stays_absent():
    assert m.ship_type(None) is None


# --- MMSI station kind and flag ---------------------------------------------

@pytest.mark.parametrize("mmsi,kind", [
    ("563028460", "ship"),
    ("995331385", "aid to navigation"),
    ("982470123", "craft associated with parent ship"),
    ("003669145", "coast station"),
    ("111232512", "search and rescue aircraft"),
    ("970123456", "emergency beacon"),
    ("9135649", "malformed"),
])
def test_mmsi_station_kinds(mmsi, kind):
    """S02 found the feed carries objects that are not ships."""
    assert m.mmsi_kind(mmsi) == kind


@pytest.mark.parametrize("mmsi,flag", [
    ("533012345", "Malaysia"),      # matches the bundled snapshot, which predates S02
    ("477055221", "Hong Kong"),     # likewise
    ("563028460", "Singapore"),
    ("636021217", "Liberia"),
    ("538012415", "Marshall Islands"),
])
def test_flag_from_ordinary_ship_mmsi(mmsi, flag):
    assert m.flag_from_mmsi(mmsi) == flag


def test_aid_to_navigation_takes_country_digits_from_the_middle():
    """AC-6, and the exact bug S02 found.

    An aid to navigation is 99MIDxxxx, so the country digits sit at positions
    2 to 5. Reading the first three gives 995, which is not a country at all.
    """
    assert m.flag_from_mmsi("995331385") == "Malaysia"
    assert m.mmsi_kind("995331385") == "aid to navigation"


def test_malformed_mmsi_yields_no_flag_rather_than_a_wrong_one():
    assert m.flag_from_mmsi("9135649") is None


def test_unallocated_country_digits_yield_none():
    assert m.flag_from_mmsi("999999999") is None


# --- length ------------------------------------------------------------------

def test_length_is_bow_plus_stern_offsets():
    """Checked against ALS CERES, a real captured vessel: A=194 B=61 -> 255m."""
    assert m.length_from_dimension({"A": 194, "B": 61, "C": 24, "D": 19}) == 255


def test_zero_dimensions_mean_unknown_not_a_zero_metre_ship():
    """S03 D-3. A vessel transmitting zeroes has not told us its length."""
    assert m.length_from_dimension({"A": 0, "B": 0, "C": 0, "D": 0}) is None


@pytest.mark.parametrize("bad", [None, {}, {"A": 10}, {"A": "x", "B": 5}, "nope", 42])
def test_length_handles_rubbish_without_raising(bad):
    assert m.length_from_dimension(bad) is None


# --- time --------------------------------------------------------------------

def test_parses_the_real_go_timestamp_format():
    """MetaData.time_utc is Go formatting, not ISO 8601. fromisoformat rejects it."""
    got = m.parse_time("2026-09-14 06:13:12.762181384 +0000 UTC")
    assert got == datetime(2026, 9, 14, 6, 13, 12, 762181, tzinfo=timezone.utc)


def test_parses_a_timestamp_without_fractional_seconds():
    assert m.parse_time("2026-09-14 06:13:12 +0000 UTC") == \
        datetime(2026, 9, 14, 6, 13, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", [None, "", "not a time", "2026-13-45 99:99:99 +0000 UTC", 12345])
def test_unparseable_time_returns_none_rather_than_raising(bad):
    assert m.parse_time(bad) is None


# --- strings -----------------------------------------------------------------

def test_padding_is_trimmed():
    """AIS pads to a fixed width. Real capture: "SEA LONGEVITY       "."""
    assert m.clean("SEA LONGEVITY       ") == "SEA LONGEVITY"


def test_a_field_of_only_spaces_is_absent_not_empty_string():
    assert m.clean("        ") is None


@pytest.mark.parametrize("bad", [None, 42, {}, []])
def test_clean_ignores_non_strings(bad):
    assert m.clean(bad) is None


# --- envelope and record -----------------------------------------------------

def test_identity_comes_from_the_metadata_envelope():
    """S02 D-1: identity rides on every message, not only on ShipStaticData."""
    got = m.identity({"MetaData": {"MMSI": 563028460,
                                   "ShipName": "SEA LONGEVITY       ",
                                   "time_utc": "2026-09-14 06:13:12.0 +0000 UTC"}})
    assert got["mmsi"] == "563028460"
    assert got["name"] == "SEA LONGEVITY"
    assert got["observed_at"] == datetime(2026, 9, 14, 6, 13, 12, tzinfo=timezone.utc)


def test_a_record_has_exactly_the_snapshot_keys():
    """The bundled snapshot is the contract. No key missing, no key extra."""
    expected = {"mmsi", "name", "type", "flag", "lat", "lon",
                "speed_knots", "length_m", "destination", "nearest_port", "status"}
    assert set(m.to_record(mmsi="533012345")) == expected


def test_position_only_record_leaves_identity_fields_null():
    """G8 and AC-5 of S02: nothing is invented and nothing is defaulted."""
    rec = m.to_record(
        position={"Latitude": 3.0, "Longitude": 101.4, "Sog": 11.2, "NavigationalStatus": 1},
        name="LNG GLORY", mmsi="314309000")
    assert rec["lat"] == 3.0
    assert rec["speed_knots"] == 11.2
    assert rec["status"] == "At anchor"
    assert rec["flag"] == "Barbados"         # derived from the MMSI, not transmitted
    assert rec["type"] is None
    assert rec["length_m"] is None
    assert rec["destination"] is None


def test_static_data_fills_the_identity_half():
    rec = m.to_record(
        position={"Latitude": 1.26, "Longitude": 103.79, "Sog": 0.0, "NavigationalStatus": 5},
        static={"Type": 70, "Destination": "MYTTP               ",
                "Dimension": {"A": 194, "B": 61, "C": 24, "D": 19}},
        name="ALS CERES", mmsi="563186500")
    assert rec["type"] == "Cargo"
    assert rec["length_m"] == 255
    assert rec["destination"] == "MYTTP"
    assert rec["status"] == "Moored"


def test_destination_free_text_is_passed_through_not_normalised():
    """S02 found real values like OMSLL>SGSIN. Cleaning them would invent meaning."""
    rec = m.to_record(static={"Destination": "OMSLL>SGSIN   "}, mmsi="533012345")
    assert rec["destination"] == "OMSLL>SGSIN"


def test_position_fields_extracts_only_the_position_half():
    """Direct cover. to_record exercises it indirectly, which is not the same
    thing as knowing what it returns on its own."""
    got = m.position_fields({"Latitude": 1.26, "Longitude": 103.79,
                             "Sog": 12.5, "NavigationalStatus": 1})
    assert got == {"lat": 1.26, "lon": 103.79,
                   "speed_knots": 12.5, "status": "At anchor"}


def test_position_fields_on_a_class_b_body_reports_no_status():
    got = m.position_fields({"Latitude": 1.24, "Longitude": 103.80, "Sog": 8.6})
    assert got["status"] is None
    assert got["speed_knots"] == 8.6


def test_static_fields_extracts_only_the_identity_half():
    got = m.static_fields({"Type": 80, "Destination": "SGSIN   ",
                           "Dimension": {"A": 150, "B": 50, "C": 10, "D": 10}})
    assert got == {"type": "Tanker", "destination": "SGSIN", "length_m": 200}


def test_static_fields_on_an_empty_body_returns_all_none():
    assert m.static_fields({}) == {"type": None, "destination": None, "length_m": None}


def test_class_b_position_report_has_no_status_field():
    """It is a real message type and it carries no NavigationalStatus at all."""
    rec = m.to_record(position={"Latitude": 1.24, "Longitude": 103.80, "Sog": 8.6},
                      mmsi="312113000")
    assert rec["status"] is None
    assert rec["lat"] == 1.24
