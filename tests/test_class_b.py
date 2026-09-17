"""Class B identity: the 8.6% of traffic this server used to discard.

Class A vessels send ShipStaticData (message 5) and the server has always read
it. Class B vessels do not send message 5 at all. They send StaticDataReport
(message 24) in two halves, and some send ExtendedClassBPositionReport
(message 19) which carries identity and position together. Neither was parsed,
so every Class B vessel was "Type not reported" however long it stayed in view.

Fixture: tests/data/ais_class_b_capture.json, 75 real messages taken from
Southeast Asian water on 2026-09-17. The older fixture contains zero message 24
because it was captured over Malaysian water where Class B traffic is thin,
which is how this gap survived a test suite (G7).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maritime_mcp_server import ais_mapping
from maritime_mcp_server.store import VesselStore

CAPTURE = Path(__file__).parent / "data" / "ais_class_b_capture.json"


@pytest.fixture(scope="module")
def captured():
    return json.loads(CAPTURE.read_text())


def _of(messages, kind):
    return [m for m in messages if m.get("MessageType") == kind]


# --- the fixture is the point, so check it is what it claims to be -----------

def test_the_capture_contains_the_message_types_this_module_is_about(captured):
    for kind in ("StaticDataReport", "ExtendedClassBPositionReport"):
        assert _of(captured, kind), f"the fixture has no {kind} in it"


# --- ship type 0 -------------------------------------------------------------

def test_ship_type_zero_is_absence_not_a_category():
    """Code 0 is "not available" in the standard. It was rendering as
    "Unknown type 0", which reads as a category rather than as no answer, and
    appeared in the dashboard legend as exactly that."""
    assert ais_mapping.ship_type(0) is None
    assert ais_mapping.ship_type(None) is None
    # A code that is genuinely unrecognised still reports itself (G8).
    assert ais_mapping.ship_type(99) == "Other"
    assert ais_mapping.ship_type(7) == "Unknown type 7"


# --- message 19 --------------------------------------------------------------

def test_extended_class_b_is_treated_as_a_position(captured):
    """It carries a position, so a vessel sending only these was invisible."""
    assert "ExtendedClassBPositionReport" in ais_mapping.POSITION_TYPES
    body = _of(captured, "ExtendedClassBPositionReport")[0]["Message"][
        "ExtendedClassBPositionReport"]
    fields = ais_mapping.position_fields(body)
    assert fields["lat"] is not None and fields["lon"] is not None


def test_extended_class_b_also_carries_identity(captured):
    found = None
    for m in _of(captured, "ExtendedClassBPositionReport"):
        got = ais_mapping.class_b_identity(m["MessageType"],
                                           m["Message"]["ExtendedClassBPositionReport"])
        if got.get("type"):
            found = got
            break
    assert found, "no captured message 19 established a type"
    assert found["name"]
    assert found["type"]


def test_class_b_position_has_no_navigational_status(captured):
    """Class B does not report one, and inventing "Under way" would be a lie."""
    body = _of(captured, "ExtendedClassBPositionReport")[0]["Message"][
        "ExtendedClassBPositionReport"]
    assert ais_mapping.position_fields(body)["status"] is None


# --- message 24, which arrives in halves -------------------------------------

def test_part_a_gives_a_name_and_claims_no_type():
    body = {"PartNumber": False,
            "ReportA": {"Name": "SANKOSHOMA          ", "Valid": True},
            "ReportB": {"CallSign": "", "ShipType": 0, "Valid": False}}
    got = ais_mapping.class_b_identity("StaticDataReport", body)
    assert got == {"name": "SANKOSHOMA"}


def test_part_b_gives_a_type_and_length_and_claims_no_name():
    body = {"PartNumber": True,
            "ReportA": {"Name": "", "Valid": False},
            "ReportB": {"CallSign": "JZON", "ShipType": 80,
                        "Dimension": {"A": 50, "B": 12, "C": 6, "D": 6}, "Valid": True}}
    got = ais_mapping.class_b_identity("StaticDataReport", body)
    assert got == {"type": "Tanker", "length_m": 62}


def test_an_invalid_half_contributes_nothing():
    """Valid is the field that says which half this message actually is."""
    body = {"PartNumber": False,
            "ReportA": {"Name": "GHOST", "Valid": False},
            "ReportB": {"ShipType": 80, "Valid": False}}
    assert ais_mapping.class_b_identity("StaticDataReport", body) == {}


# --- merging, which is where a partial message could do damage ---------------

def _msg(kind, body, mmsi="525000001", name=None):
    return {"MessageType": kind,
            "MetaData": {"MMSI": mmsi, "ShipName": name,
                         "time_utc": "2026-09-17 06:00:00.000000000 +0000 UTC"},
            "Message": {kind: body}}


def _record(store, mmsi="525000001"):
    return next(r for r in store.records(require_position=False) if r["mmsi"] == mmsi)


def test_the_two_halves_combine_into_one_vessel():
    store = VesselStore()
    store.ingest(_msg("StaticDataReport",
                      {"ReportA": {"Name": "SRI PERMAISURI", "Valid": True},
                       "ReportB": {"Valid": False}}))
    store.ingest(_msg("StaticDataReport",
                      {"ReportA": {"Valid": False},
                       "ReportB": {"ShipType": 52, "Valid": True,
                                   "Dimension": {"A": 10, "B": 12, "C": 4, "D": 4}}}))
    record = _record(store)
    assert record["name"] == "SRI PERMAISURI"
    assert record["type"] == "Tug"
    assert record["length_m"] == 22


def test_a_later_partial_message_does_not_blank_what_is_known():
    """Part A arrives roughly three times as often as part B, so a name-only
    message landing after a type is the common case, not the edge case."""
    store = VesselStore()
    store.ingest(_msg("StaticDataReport",
                      {"ReportA": {"Valid": False},
                       "ReportB": {"ShipType": 30, "Valid": True}}))
    assert _record(store)["type"] == "Fishing"
    store.ingest(_msg("StaticDataReport",
                      {"ReportA": {"Name": "NELAYAN SATU", "Valid": True},
                       "ReportB": {"Valid": False}}))
    record = _record(store)
    assert record["type"] == "Fishing", "the type was blanked by a name-only message"
    assert record["name"] == "NELAYAN SATU"


def test_class_a_static_is_not_overwritten_by_a_class_b_report():
    """A vessel sending both should keep the fuller Class A answer."""
    store = VesselStore()
    store.ingest(_msg("ShipStaticData",
                      {"Type": 70, "Destination": "SINGAPORE",
                       "Dimension": {"A": 100, "B": 50, "C": 10, "D": 10}}))
    store.ingest(_msg("StaticDataReport",
                      {"ReportA": {"Valid": False},
                       "ReportB": {"ShipType": 30, "Valid": True}}))
    record = _record(store)
    assert record["type"] == "Cargo"
    assert record["destination"] == "SINGAPORE"


# --- the whole point, measured -----------------------------------------------

def test_the_captured_traffic_now_yields_types(captured):
    """Before this change none of these messages were parsed at all, so every
    one of these vessels was "Type not reported"."""
    store = VesselStore()
    for message in captured:
        store.ingest(message)
    records = store.records(require_position=False)
    typed = [r for r in records if r.get("type")]
    assert len(records) > 40, "the fixture should produce a decent number of vessels"
    assert len(typed) >= 20, f"only {len(typed)} of {len(records)} got a type"


# --- what gets written down --------------------------------------------------

def test_a_navigation_buoy_is_not_written_into_the_history(tmp_path):
    """records() dropped non-ships from the live view from the start, so the map
    was right while the history filled up with them. Measured on the production
    database: 11 aids to navigation, 8 malformed identifiers and 3 craft
    associated with a parent ship, one of which appeared in a port call probe as
    a vessel that had been stationary for two days."""
    from maritime_mcp_server.history import VesselHistory

    history = VesselHistory(path=str(tmp_path / "v.db"))
    store = VesselStore(history=history)

    position = {"Latitude": 2.5, "Longitude": 101.8, "Sog": 0.0,
                "NavigationalStatus": 0, "Cog": 0.0, "TrueHeading": 511}
    store.ingest(_msg("PositionReport", position, mmsi="995331385"))   # aid to navigation
    store.ingest(_msg("PositionReport", position, mmsi="1234567"))     # malformed
    store.ingest(_msg("PositionReport", position, mmsi="533012345"))   # a real ship

    written = {row["mmsi"] for row in history.latest_positions(
        __import__("datetime").datetime(2000, 1, 1,
                                        tzinfo=__import__("datetime").timezone.utc))}
    assert written == {"533012345"}
    history.close()


def test_a_stale_unknown_type_zero_is_cleared_on_open(tmp_path):
    """Fixing ship_type() stopped new bad labels but not old ones. The stored
    identity table is rehydrated into the live view, so 89 rows written before
    the fix kept putting "Unknown type 0" back on the map."""
    import sqlite3
    from maritime_mcp_server.history import VesselHistory

    path = str(tmp_path / "v.db")
    history = VesselHistory(path=path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO vessels (mmsi, type) VALUES ('1', 'Unknown type 0')")
    conn.execute("INSERT INTO vessels (mmsi, type) VALUES ('2', 'Unknown type 9')")
    conn.execute("INSERT INTO vessels (mmsi, type) VALUES ('3', 'Tanker')")
    conn.commit()
    conn.close()
    history.close()

    VesselHistory(path=path).close()          # reopening runs the migration

    conn = sqlite3.connect(path)
    kept = dict(conn.execute("SELECT mmsi, type FROM vessels").fetchall())
    conn.close()
    assert kept["1"] is None
    # A genuinely unrecognised code still reports itself (G8).
    assert kept["2"] == "Unknown type 9"
    assert kept["3"] == "Tanker"
