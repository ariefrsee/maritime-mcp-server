"""Translate AIS wire messages into this server's vessel record shape.

Pure functions, no network, no state. Every lookup here falls through to a
readable "unknown" value that carries the raw code rather than guessing, because
a wrong label that looks right is worse than an honest gap.

Field names and nesting were taken from 375 seconds of real traffic captured over
Malaysian waters on 2026-09-14, not from the published schema alone. That capture
is committed at tests/data/ais_capture.json. Two things it corrected:

    * Identity (MMSI, ship name, a real UTC timestamp) rides in MetaData on every
      message, so it does not require merging ShipStaticData.
    * The Timestamp field inside the message body is the second of the minute,
      not a clock. MetaData.time_utc is the usable time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files

MID_FILE = files(__package__).joinpath("data/mid_countries.json")

# Message types that carry a position. Class B units are fitted to smaller
# vessels and report a reduced field set, notably with no navigational status.
POSITION_TYPES = ("PositionReport", "StandardClassBPositionReport")

# ITU navigational status, 0 to 15.
NAV_STATUS = {
    0: "Under way using engine",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by her draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way sailing",
    9: "Reserved for high speed craft",
    10: "Reserved for wing in ground craft",
    11: "Power driven vessel towing astern",
    12: "Power driven vessel pushing ahead",
    13: "Reserved",
    14: "AIS SART, MOB or EPIRB",
    15: "Undefined",
}

# AIS ship type is decade coded. The decade gives the broad category and a few
# specific codes are worth naming on their own.
TYPE_DECADES = {
    2: "Wing in ground craft",
    3: "Special craft",
    4: "High speed craft",
    5: "Special craft",
    6: "Passenger",
    7: "Cargo",
    8: "Tanker",
    9: "Other",
}
TYPE_SPECIFIC = {
    30: "Fishing",
    31: "Tug",
    32: "Tug",
    33: "Dredger",
    34: "Diving vessel",
    35: "Military",
    36: "Sailing vessel",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti pollution vessel",
    55: "Law enforcement",
    58: "Medical transport",
}


@lru_cache(maxsize=1)
def _mid_table() -> dict:
    return json.loads(MID_FILE.read_text(encoding="utf-8"))


def clean(value) -> str | None:
    """AIS pads strings with spaces. Empty after trimming means absent."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def navigational_status(code) -> str | None:
    """Map an ITU navigational status code to words.

    Returns None when the field is absent, which is normal for Class B reports.
    An unrecognised code is reported as itself rather than guessed at.
    """
    if code is None:
        return None
    if code in NAV_STATUS:
        return NAV_STATUS[code]
    return f"Unknown status {code}"


def ship_type(code) -> str | None:
    """Map an AIS ship type code to a category."""
    if code is None:
        return None
    if code in TYPE_SPECIFIC:
        return TYPE_SPECIFIC[code]
    decade = code // 10
    if decade in TYPE_DECADES:
        return TYPE_DECADES[decade]
    return f"Unknown type {code}"


# Not every AIS transmitter is a ship. The MMSI prefix says what it is, and the
# country digits are not always at the front. Real Malaysian traffic contained
# an aid to navigation (995331385) and a malformed seven digit identifier, both
# of which would otherwise have been listed as vessels.
def mmsi_kind(mmsi) -> str:
    """Classify an MMSI: ship, aid to navigation, base station and so on."""
    digits = str(mmsi).strip() if mmsi is not None else ""
    if not digits.isdigit() or len(digits) != 9:
        return "malformed"
    if digits.startswith("00"):
        return "coast station"
    if digits.startswith("0"):
        return "group of ships"
    if digits.startswith("111"):
        return "search and rescue aircraft"
    if digits.startswith("99"):
        return "aid to navigation"
    if digits.startswith("98"):
        return "craft associated with parent ship"
    if digits.startswith(("970", "972", "974")):
        return "emergency beacon"
    return "ship"


def _mid_digits(mmsi) -> str | None:
    """Where the country digits live depends on what kind of station it is."""
    digits = str(mmsi).strip() if mmsi is not None else ""
    kind = mmsi_kind(mmsi)
    if kind == "ship":
        return digits[:3]
    if kind in ("aid to navigation", "craft associated with parent ship"):
        return digits[2:5]
    if kind == "coast station":
        return digits[2:5]
    if kind == "search and rescue aircraft":
        return digits[3:6]
    return None


def flag_from_mmsi(mmsi) -> str | None:
    """Derive the flag state from the Maritime Identification Digits.

    The flag is not transmitted over AIS. The MMSI carries three ITU allocated
    country digits, so they are the only available source. Their position within
    the number depends on the station type, which is why this defers to
    _mid_digits rather than always taking the first three.
    """
    mid = _mid_digits(mmsi)
    if not mid or not mid.isdigit():
        return None
    return _mid_table().get(mid)


def length_from_dimension(dimension) -> int | None:
    """Overall length in metres, from the reference point offsets.

    A is bow to reference point, B is reference point to stern, so A + B is the
    length overall. Not transmitted directly.
    """
    if not isinstance(dimension, dict):
        return None
    a, b = dimension.get("A"), dimension.get("B")
    if not isinstance(a, int) or not isinstance(b, int):
        return None
    total = a + b
    return total or None


def parse_time(value) -> datetime | None:
    """Parse MetaData.time_utc.

    Observed format: "2026-09-14 06:13:12.762181384 +0000 UTC", which is Go's
    time formatting and is not ISO 8601. Nanoseconds and the trailing zone name
    both need handling.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(" UTC"):
        text = text[:-4]
    date_part, _, rest = text.partition(" ")
    clock_part, _, zone = rest.partition(" ")
    if "." in clock_part:
        head, _, frac = clock_part.partition(".")
        clock_part = f"{head}.{frac[:6]}"
    candidate = f"{date_part} {clock_part}"
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def identity(message) -> dict:
    """Pull MMSI, name and observation time out of the MetaData envelope."""
    meta = message.get("MetaData") or {}
    mmsi = meta.get("MMSI")
    return {
        "mmsi": str(mmsi) if mmsi is not None else None,
        "name": clean(meta.get("ShipName")),
        "observed_at": parse_time(meta.get("time_utc")),
    }


def position_fields(body) -> dict:
    """The position half of a record, from either position message type."""
    return {
        "lat": body.get("Latitude"),
        "lon": body.get("Longitude"),
        "speed_knots": body.get("Sog"),
        "status": navigational_status(body.get("NavigationalStatus")),
    }


def static_fields(body) -> dict:
    """The identity half of a record, from ShipStaticData."""
    return {
        "type": ship_type(body.get("Type")),
        "destination": clean(body.get("Destination")),
        "length_m": length_from_dimension(body.get("Dimension")),
    }


def to_record(position=None, static=None, name=None, mmsi=None) -> dict:
    """Fold what is known about one vessel into the server's record shape.

    Every key the bundled snapshot has is present. Anything not known is None.
    Nothing is invented and nothing is defaulted to a plausible looking value,
    because a vessel known only by its MMSI is still a true answer.
    """
    record = {
        "mmsi": mmsi,
        "name": name,
        "type": None,
        "flag": flag_from_mmsi(mmsi),
        "lat": None,
        "lon": None,
        "speed_knots": None,
        "length_m": None,
        "destination": None,
        "nearest_port": None,
        "status": None,
    }
    if position:
        record.update(position_fields(position))
    if static:
        record.update(static_fields(static))
    return record
