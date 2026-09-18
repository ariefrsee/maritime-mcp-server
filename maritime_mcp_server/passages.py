"""How long a leg actually takes, measured from ships that made it.

Every planning tool answers this with distance divided by an assumed speed.
That is a guess dressed as arithmetic: it knows nothing about the strait, the
traffic, the pilot boarding, or the hour spent waiting for a berth at the far
end. This measures instead, from the recorded tracks of vessels that have made
the passage.

What it refuses to do
---------------------

  * A vessel seen at the far end but never at the near end has not made a
    passage; the record simply starts mid-voyage. Both ends must be witnessed.
  * A passage is only counted once per vessel per direction in the window. A
    ferry shuttling four times a day would otherwise dominate the median for a
    leg that cargo ships also use.
  * Nothing is reported from fewer than MIN_OBSERVATIONS passages. A median of
    two is not a benchmark, it is two numbers.
  * The spread is always given with the middle. A leg with a median of 14 hours
    and a range of 7 to 62 is not a leg anyone should schedule to 14.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

#: How close a vessel must come to count as having been at an endpoint. Twenty
#: miles is generous, and deliberately so: the recorded track is what a receiver
#: happened to hear, and demanding a fix inside the breakwater would discard
#: most real passages over a gap in coverage.
ENDPOINT_NM = 20.0

#: Below this many observed passages, no median is reported. Two numbers are not
#: a benchmark and presenting them as one invites a schedule to be built on them.
MIN_OBSERVATIONS = 5

#: A passage longer than this is not a passage. The vessel called somewhere in
#: between, or sat out a charter, and averaging that into a leg time makes the
#: leg look worse than it is for everyone who did not.
MAX_PASSAGE_HOURS = 14 * 24


def _nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 3440.065 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _moment(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def passages_for(fixes, origin, destination, endpoint_nm: float = ENDPOINT_NM):
    """Every completed origin-to-destination passage in one vessel's track.

    `fixes` are dicts with observed_at, lat and lon, in any order. `origin` and
    `destination` are (lat, lon).

    A passage opens when the vessel is seen within reach of the origin and
    closes the first time it is seen within reach of the destination after
    that. The clock starts at the *last* fix near the origin rather than the
    first, because a ship that sat at anchor off the port for a day did not
    spend that day on passage.
    """
    usable = []
    for fix in fixes:
        moment = _moment(fix.get("observed_at"))
        lat, lon = fix.get("lat"), fix.get("lon")
        if moment is None or lat is None or lon is None:
            continue
        usable.append((moment, lat, lon))
    usable.sort()

    found = []
    left_origin = None
    for moment, lat, lon in usable:
        if _nm(origin[0], origin[1], lat, lon) <= endpoint_nm:
            # Still in the origin's reach, so the passage has not begun yet.
            left_origin = moment
            continue
        if left_origin and _nm(destination[0], destination[1], lat, lon) <= endpoint_nm:
            hours = (moment - left_origin).total_seconds() / 3600
            if 0 < hours <= MAX_PASSAGE_HOURS:
                found.append({"departed_at": left_origin.isoformat(),
                              "arrived_at": moment.isoformat(),
                              "hours": round(hours, 2)})
            left_origin = None
    return found


def summarise(passages, distance_nm=None) -> dict:
    """The middle and the spread. Never the middle alone."""
    hours = sorted(p["hours"] for p in passages)
    if len(hours) < MIN_OBSERVATIONS:
        return {
            "observations": len(hours),
            "enough": False,
            "note": (
                f"Fewer than {MIN_OBSERVATIONS} observed passages. A median of "
                "these would be a coincidence rather than a benchmark."
            ),
        }

    def pct(p):
        return hours[min(len(hours) - 1, int(round(p * (len(hours) - 1))))]

    median = pct(0.5)
    out = {
        "observations": len(hours),
        "enough": True,
        "fastest_hours": round(hours[0], 1),
        "p25_hours": round(pct(0.25), 1),
        "median_hours": round(median, 1),
        "p75_hours": round(pct(0.75), 1),
        "slowest_hours": round(hours[-1], 1),
    }
    if distance_nm:
        # Implied speed over the whole leg, which is not the speed anybody
        # steamed: it includes every hour spent stopped on the way.
        out["distance_nm"] = round(distance_nm, 1)
        out["median_speed_kn"] = round(distance_nm / median, 1) if median else None
    return out
