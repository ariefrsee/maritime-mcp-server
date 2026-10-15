"""Who is at a port, who is coming, and who has just left.

What this is for
----------------

A port agent's desk asks the same three questions all day. Which ships are here,
and since when. Which ships are coming. Which ships have just gone. This answers
them from the recorded positions for one port at a time, starting with Port
Dickson, where the agency this was built for works.

What the coverage allows
------------------------

Measured on 2026-10-15: a ship stopped at Port Dickson is heard about once
every 35 to 65 minutes, and about one gap in ten runs past two or three hours.
So nothing here claims a minute. An arrival is the window between the last fix
before the visit and the first fix inside it, and a ship that goes quiet is
"not heard since", never "departed". Silence is not evidence of leaving.

The rules
---------

  * A port is a circle around a centre. A visit is a vessel's fixes inside it,
    split wherever two of them are more than VISIT_GAP_HOURS apart. Leaving
    takes a fix EXIT_MARGIN_NM past the edge, so a ship working along the
    boundary is not counted out and back in.
  * A vessel has stopped when a fix reads under STOPPED_KNOTS, the same
    threshold the port call reconstruction uses. Reported status is ignored:
    every stopped vessel measured at Port Dickson said "Under way using engine".
  * A visit counts when the vessel stopped during it or declared this port. A
    ship crossing the circle on passage is in no list.
  * Harbour craft live in the port: tugs, ferries, pilot boats and the like,
    by type, or by being present on most days when their type was never heard.
    They get a list of their own so they do not bury the port calls.

Nothing reads a clock. Every function that needs the time is given `now`.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from .passages import _nm
from .port_calls import STOPPED_KNOTS, _moment, _speed

#: Inside fixes further apart than this are two visits, not one. The measured
#: routine gaps at Port Dickson reach about three hours; this is double that.
VISIT_GAP_HOURS = 6

#: Leaving takes a fix this far past the edge. Without it a ship coming in along
#: the boundary, at 7.9 nm then 8.0 then 6.5, left and arrived again inside two
#: minutes: RAINA did exactly that in the 2026-10-15 capture. A fix in the band
#: carries on a visit that has started but never starts one.
EXIT_MARGIN_NM = 1.0

#: A vessel still counts as here if her latest fix inside is this recent.
AT_PORT_HOURS = 6

#: A vessel declaring this port must have been heard this recently to be
#: listed as coming. An older fix says nothing about where she is now.
HEADING_IN_HOURS = 12

#: How far back the departed list reaches.
DEPARTED_HOURS = 48

#: How much history the board reads, plus a margin before it so a visit near
#: the start of the window can still find the fix that came before it.
LOOKBACK_HOURS = 72
EDGE_HOURS = 12

#: Present on at least this many calendar days of the residency window, and of
#: a type nobody has heard, makes a vessel a local. The window is fourteen days,
#: counted as UTC dates, so it can span fifteen.
RESIDENT_DAYS = 10
RESIDENT_WINDOW_DAYS = 14

#: Ports with a board. Keyed like PORT_COORDS in server.py, which holds the
#: centres, so a port has one name everywhere it is accepted.
#:
#: The radius comes from where ships actually stopped: 90 percent of stationary
#: fixes within 6.2 nm, the busiest cells 1.2 to 7.8 nm out, and the Kuala
#: Linggi transfer area 13 to 18 nm away kept outside.
#:
#: The aliases are the spellings found in a month of declared destinations,
#: compared after normalise_destination. The misspelling "MYPID" is not here
#: on purpose: matching typos invites false matches, and a ship that typed it
#: still appears once she is inside the circle.
BOARD_PORTS = {
    "port dickson": {
        "radius_nm": 8.0,
        "aliases": ("MY PDI", "MY PD", "MLY PDI", "PDI", "PORT DICKSON",
                    "P DICKSON", "MY P DICKSON"),
    },
}

#: AIS types that are craft of the port rather than calls at it. These are the
#: labels the mapping layer actually produces, checked against the history
#: database. There is no "Towing" label; towing vessels map to Tug.
HARBOUR_CRAFT_TYPES = frozenset({
    "Tug", "Passenger", "High speed craft", "Pilot vessel", "Pleasure craft",
    "Sailing vessel", "Fishing", "Law enforcement", "Port tender",
    "Search and rescue", "Dredger", "Diving vessel", "Military",
})

_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def normalise_destination(text) -> str:
    """A declared destination reduced to its letters, for comparing.

    Crews type the same port a dozen ways. Upper case, keep only what follows
    the last ">" because some write "FROM>TO", then drop everything that is not
    a letter. "GHJUB>MYPDI", "MY_PDI" and "MY PDI" all become "MYPDI".
    """
    if not isinstance(text, str):
        return ""
    tail = text.upper().rsplit(">", 1)[-1]
    return re.sub(r"[^A-Z]", "", tail)


def port_aliases(port: str) -> frozenset:
    """The normalised destination spellings that mean this port."""
    return frozenset(normalise_destination(a) for a in BOARD_PORTS[port]["aliases"])


def matches_port(destination, aliases) -> bool:
    """Whether a declared destination means this port.

    Exact after normalising, so "PDI" does not catch "SPDI" or "PDIX".
    """
    key = normalise_destination(destination)
    return bool(key) and key in aliases


def is_unknown_type(vessel_type) -> bool:
    """No usable type: never heard, "Other", or a code the mapping did not know."""
    return (vessel_type is None or vessel_type == "Other"
            or str(vessel_type).startswith("Unknown type"))


def residents(days_present: dict, threshold: int = RESIDENT_DAYS) -> set:
    """Vessels present on at least `threshold` days of the residency window."""
    return {mmsi for mmsi, days in days_present.items() if days >= threshold}


def is_harbour_craft(vessel_type, resident: bool) -> bool:
    """Craft of the port rather than a call at it.

    Residency only decides when the type is unknown. A tanker that has sat off
    Port Dickson for a month is a ship the agency wants to see, not a local.
    """
    if vessel_type in HARBOUR_CRAFT_TYPES:
        return True
    return resident and is_unknown_type(vessel_type)


def compass_point(centre, lat, lon) -> str:
    """Eight point bearing of a position from the port centre."""
    dlat = lat - centre[0]
    dlon = (lon - centre[1]) * math.cos(math.radians(centre[0]))
    degrees = math.degrees(math.atan2(dlon, dlat)) % 360
    return _COMPASS[int((degrees + 22.5) // 45) % 8]


def _clean(fixes) -> list[dict]:
    """Fixes with a time and a position, oldest first, speed made safe."""
    out = []
    for f in fixes:
        at = _moment(f.get("observed_at"))
        lat, lon = f.get("lat"), f.get("lon")
        if at is None or lat is None or lon is None:
            continue
        out.append({"at": at, "lat": lat, "lon": lon, "sog": _speed(f.get("sog"))})
    out.sort(key=lambda f: f["at"])
    return out


def visits(fixes, centre, radius_nm, gap_hours=VISIT_GAP_HOURS) -> list[dict]:
    """One vessel's visits to the port circle, oldest first.

    `fixes` are dicts with observed_at, lat, lon and sog, in any order. Each
    visit says how it opened and how it closed, because those are different
    claims:

      opened_by  "arrival" when the fix before it was outside the circle,
                 "gap" when it belonged to an earlier visit too long ago to span,
                 "record start" when there is no earlier fix to read.
      closed_by  "departure" when the next fix is outside the circle,
                 "gap" when the next fix is inside but too long after,
                 None when nothing has been heard since. Whether that means she
                 is still here or has gone quiet is for the caller, who knows
                 the time.
    """
    gap = timedelta(hours=gap_hours)
    found = []
    current = None
    previous = None
    previous_in_visit = False
    for fix in _clean(fixes):
        distance = _nm(centre[0], centre[1], fix["lat"], fix["lon"])
        inside = distance <= radius_nm
        beyond = distance > radius_nm + EXIT_MARGIN_NM
        if current is not None and fix["at"] - current["fixes"][-1]["at"] > gap:
            if inside or not beyond:
                current["closed_by"] = "gap"
                current["next_at"] = fix["at"]
                found.append(current)
                current = None
        if current is not None and beyond:
            current["closed_by"] = "departure"
            current["next_at"] = fix["at"]
            found.append(current)
            current = None
            previous_in_visit = False
        elif current is not None:
            current["fixes"].append(fix)
        elif inside:
            if previous is None:
                opened_by = "record start"
            elif previous_in_visit:
                opened_by = "gap"
            else:
                opened_by = "arrival"
            current = {
                "opened_by": opened_by,
                "previous_at": previous["at"] if previous else None,
                "fixes": [fix],
                "closed_by": None,
                "next_at": None,
            }
        if current is not None:
            previous_in_visit = True
        elif not inside:
            previous_in_visit = previous_in_visit and not beyond
        previous = fix
    if current is not None:
        found.append(current)
    for visit in found:
        visit["first_at"] = visit["fixes"][0]["at"]
        visit["last_at"] = visit["fixes"][-1]["at"]
        visit["stopped"] = any(f["sog"] is not None and f["sog"] < STOPPED_KNOTS
                               for f in visit["fixes"])
    return found


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


def _minutes(now: datetime, moment: datetime) -> int:
    return int((now - moment).total_seconds() // 60)


def _identity(identity: dict | None) -> dict:
    identity = identity or {}
    return {
        "name": identity.get("name"),
        "type": identity.get("type"),
        "flag": identity.get("flag"),
        "length_m": identity.get("length_m"),
    }


def _last_speed(fixes) -> float | None:
    for fix in reversed(fixes):
        if fix["sog"] is not None:
            return fix["sog"]
    return None


def build_board(fixes_by_mmsi: dict, identities: dict, days_present: dict,
                centre, radius_nm: float, aliases, now: datetime) -> dict:
    """The four lists for one port at one moment.

    `fixes_by_mmsi` holds each candidate vessel's fixes over the lookback, all
    of them rather than only the ones inside the circle, because the windows
    need the fixes either side. `identities` holds name, type, flag, length_m,
    destination and eta_declared per MMSI as recorded. `days_present` holds
    each vessel's calendar days in the port over the residency window.
    """
    now = _moment(now)
    local = residents(days_present)
    at_port, heading_in, departed, harbour_craft = [], [], [], []

    for mmsi, raw in fixes_by_mmsi.items():
        identity = identities.get(mmsi) or {}
        declared = identity.get("destination")
        bound_here = matches_port(declared, aliases)
        craft = is_harbour_craft(identity.get("type"), mmsi in local)
        fixes = _clean(raw)
        if not fixes:
            continue
        latest = fixes[-1]
        found = visits(raw, centre, radius_nm)
        here = (found and found[-1]["closed_by"] is None
                and now - found[-1]["last_at"] <= timedelta(hours=AT_PORT_HOURS))

        if craft:
            if here:
                harbour_craft.append({
                    "mmsi": mmsi, **_identity(identity),
                    "resident": mmsi in local,
                    "lat": latest["lat"], "lon": latest["lon"],
                    "distance_nm": _nm(centre[0], centre[1], latest["lat"], latest["lon"]),
                    "speed_knots": _last_speed(found[-1]["fixes"]),
                    "last_seen": _iso(found[-1]["last_at"]),
                    "last_seen_minutes": _minutes(now, found[-1]["last_at"]),
                })
            continue

        left_recently = False
        for visit in found:
            if not (visit["stopped"] or bound_here):
                continue
            is_latest = visit is found[-1]
            if is_latest and here:
                at_port.append({
                    "mmsi": mmsi, **_identity(identity),
                    "lat": latest["lat"], "lon": latest["lon"],
                    "distance_nm": _nm(centre[0], centre[1], latest["lat"], latest["lon"]),
                    "bearing": compass_point(centre, latest["lat"], latest["lon"]),
                    "opened_by": visit["opened_by"],
                    "arrived_after": _iso(visit["previous_at"]),
                    "arrived_by": _iso(visit["first_at"]),
                    "stopped": visit["stopped"],
                    "hours_seen": round((visit["last_at"] - visit["first_at"]).total_seconds() / 3600, 1),
                    "speed_knots": _last_speed(visit["fixes"]),
                    "last_seen": _iso(visit["last_at"]),
                    "last_seen_minutes": _minutes(now, visit["last_at"]),
                    "destination": declared,
                    "eta_declared": identity.get("eta_declared"),
                })
                continue
            # Leaving is about calls. A ship that never stopped and then went
            # is not a departure from this port, whatever she declared.
            if visit["closed_by"] == "gap" or not visit["stopped"]:
                continue
            if now - visit["last_at"] > timedelta(hours=DEPARTED_HOURS):
                continue
            left_recently = True
            departed.append({
                "mmsi": mmsi, **_identity(identity),
                "opened_by": visit["opened_by"],
                "arrived_after": _iso(visit["previous_at"]),
                "arrived_by": _iso(visit["first_at"]),
                "left_after": _iso(visit["last_at"]),
                "left_by": _iso(visit["next_at"]),
                "silent": visit["closed_by"] is None,
                "hours_seen": round((visit["last_at"] - visit["first_at"]).total_seconds() / 3600, 1),
                "destination": declared,
            })

        if (bound_here and not here and not left_recently
                and now - latest["at"] <= timedelta(hours=HEADING_IN_HOURS)
                and _nm(centre[0], centre[1], latest["lat"], latest["lon"]) > radius_nm):
            heading_in.append({
                "mmsi": mmsi, **_identity(identity),
                "lat": latest["lat"], "lon": latest["lon"],
                "distance_nm": _nm(centre[0], centre[1], latest["lat"], latest["lon"]),
                "speed_knots": latest["sog"],
                "last_seen": _iso(latest["at"]),
                "last_seen_minutes": _minutes(now, latest["at"]),
                "destination": declared,
                "eta_declared": identity.get("eta_declared"),
            })

    at_port.sort(key=lambda r: r["arrived_by"], reverse=True)
    heading_in.sort(key=lambda r: r["distance_nm"])
    departed.sort(key=lambda r: r["left_after"], reverse=True)
    harbour_craft.sort(key=lambda r: (r["name"] is None, r["name"] or "", r["mmsi"]))
    return {"at_port": at_port, "heading_in": heading_in,
            "departed": departed, "harbour_craft": harbour_craft}
