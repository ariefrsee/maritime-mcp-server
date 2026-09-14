"""Builders and constants shared by the test modules.

Kept out of conftest.py so the test modules can import it by name. pytest puts
each test file's directory on sys.path, so `from helpers import ...` works
regardless of how pytest was invoked, whereas `from tests.conftest import ...`
only works when the repository root happens to be importable.
"""

from __future__ import annotations

from datetime import datetime, timezone

# The fixture was captured on this date, so tests that replay it pin their clock
# here rather than to "now", which would evict every entry.
CAPTURE_DAY = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)


def message(kind, mmsi, when="2026-09-14 06:00:00.0 +0000 UTC", name="", **body):
    """Build one aisstream envelope. Keeps the test bodies readable."""
    return {
        "MessageType": kind,
        "MetaData": {"MMSI": mmsi, "ShipName": name, "time_utc": when},
        "Message": {kind: {"UserID": mmsi, "Valid": True, **body}},
    }


def position(mmsi, lat=3.0, lon=101.4, **kw):
    return message("PositionReport", mmsi, Latitude=lat, Longitude=lon,
                   Sog=kw.pop("sog", 10.0),
                   NavigationalStatus=kw.pop("status", 0), **kw)


def static(mmsi, **kw):
    return message("ShipStaticData", mmsi,
                   Type=kw.pop("type_code", 70),
                   Destination=kw.pop("destination", "MYPKG  "),
                   Dimension=kw.pop("dimension", {"A": 100, "B": 80, "C": 10, "D": 10}),
                   **kw)
