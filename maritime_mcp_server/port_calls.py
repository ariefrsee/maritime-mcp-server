"""Reconstructing port calls from recorded positions.

What this is for
----------------

A ship agent's Statement of Facts is a timeline: anchored at, all fast,
commenced, completed, sailed. Those times are argued over months later when
demurrage is claimed, and today they are typed by hand from memory and emails.
The recorded track already contains most of them, so this reads them out.

What it refuses to do
---------------------

Everything here is observation, not inference. A call is only reported where the
positions actually show it:

  * A vessel is stopped when she reports under half a knot, not when she is
    near a berth. Proximity is not arrival.
  * A stop is only closed when she is seen moving again. A vessel that has not
    been seen to leave is reported as still alongside, with no departure time,
    rather than being given one.
  * A stop spanning a gap longer than MAX_GAP_MINUTES is cut at the gap. AIS
    coverage is patchy and a twelve hour hole is not evidence that she sat
    there for twelve hours; it is evidence of nothing at all.
  * A stop further than MAX_PORT_DISTANCE_NM from any known port is reported as
    a stop at sea, not attributed to the nearest port name.

Anchored and moored are kept apart. In laytime terms they are opposite: one is
waiting and the other is working, and collapsing them would destroy the only
distinction the record is really being consulted for.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: Under this, a vessel is stopped. Above zero because GPS noise and a ship
#: swinging at anchor both register a little way through the water.
STOPPED_KNOTS = 0.5

#: Over this, she is under way rather than drifting, so a stop has ended.
#: The band between the two is deliberately ignored: a vessel creeping at one
#: knot is neither, and flipping between states on that would manufacture calls.
MOVING_KNOTS = 3.0

#: Shorter than this is traffic, a lock, or a pilot boarding, not a call.
MIN_STOP_MINUTES = 45

#: A hole in coverage longer than this breaks a stop rather than spanning it.
MAX_GAP_MINUTES = 60

#: Beyond this from any known port, a stop is at sea and is named as such.
MAX_PORT_DISTANCE_NM = 25.0

#: AIS sends speed over ground in 0.1 knot steps where 1023 means "not
#: available". Scaled that arrives as 102.3, which is not a speed and must not
#: be read as one: it would end every stop it touched.
SOG_UNAVAILABLE = 102.2


def _moment(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _speed(value):
    """A usable speed, or None. The sentinel is not a speed."""
    if value is None:
        return None
    try:
        knots = float(value)
    except (TypeError, ValueError):
        return None
    if knots < 0 or knots > SOG_UNAVAILABLE:
        return None
    return knots


def _dominant_status(statuses):
    """What she was mostly reporting while stopped.

    Mode rather than last value: a single stray "Under way using engine" as the
    engines come on should not relabel eleven hours at anchor.
    """
    tally = {}
    for status in statuses:
        if status:
            tally[status] = tally.get(status, 0) + 1
    if not tally:
        return None
    return max(tally.items(), key=lambda kv: kv[1])[0]


def find_calls(fixes, nearest_port, now=None) -> list[dict]:
    """Port calls visible in one vessel's recorded positions, oldest first.

    `fixes` are dicts with observed_at, lat, lon, sog and status, in any order.
    `nearest_port` takes (lat, lon) and returns (name, distance_nm).
    """
    usable = []
    for fix in fixes:
        moment = _moment(fix.get("observed_at"))
        lat, lon = fix.get("lat"), fix.get("lon")
        if moment is None or lat is None or lon is None:
            continue
        usable.append({"at": moment, "lat": lat, "lon": lon,
                       "sog": _speed(fix.get("sog")), "status": fix.get("status")})
    usable.sort(key=lambda f: f["at"])

    calls = []
    run = None
    seen_moving = False

    def close(run, departed_at):
        minutes = (run["last"] - run["first"]).total_seconds() / 60
        if minutes < MIN_STOP_MINUTES:
            return
        port, distance = nearest_port(run["lat"], run["lon"])
        at_sea = port is None or distance is None or distance > MAX_PORT_DISTANCE_NM
        calls.append({
            "port": None if at_sea else port,
            "distance_nm": None if distance is None else round(distance, 1),
            "at_sea": at_sea,
            "arrived_at": run["first"].isoformat(),
            "departed_at": departed_at.isoformat() if departed_at else None,
            "still_there": departed_at is None,
            "hours": round(minutes / 60, 1),
            "status": _dominant_status(run["statuses"]),
            "lat": round(run["lat"], 4),
            "lon": round(run["lon"], 4),
            "fix_count": run["n"],
            # An arrival is only witnessed if she was seen moving beforehand.
            # Without that the record starts mid-stop and the arrival time is
            # just when this server happened to start listening.
            "arrival_observed": run["arrival_observed"],
        })

    for fix in usable:
        speed = fix["sog"]

        if run is not None:
            # Measured from the last time she was heard at all, not from the
            # last time she was seen stopped. A vessel creeping at a knot, or
            # reporting the speed sentinel, is still being received; treating
            # that as a hole in coverage split single calls into several.
            gap = (fix["at"] - run["heard"]).total_seconds() / 60
            if gap > MAX_GAP_MINUTES:
                # Cut at the hole. What happened inside it is not known, so the
                # stop ends where the evidence ends and no departure is claimed.
                close(run, None)
                run = None
                # And nothing after the hole counts as a witnessed arrival: she
                # may have sailed and come back, or never moved. Carrying the
                # earlier sighting across would claim an arrival nobody saw.
                seen_moving = False

        if speed is None:
            # Heard, but she did not say how fast. Keeps the coverage clock
            # running without touching the stop itself.
            if run is not None:
                run["heard"] = fix["at"]
            continue

        if speed >= MOVING_KNOTS:
            if run is not None:
                close(run, fix["at"])
                run = None
            seen_moving = True
            continue

        if speed < STOPPED_KNOTS:
            if run is None:
                run = {"first": fix["at"], "last": fix["at"], "heard": fix["at"],
                       "lat": fix["lat"], "lon": fix["lon"],
                       "statuses": [fix["status"]], "n": 1,
                       "arrival_observed": seen_moving}
            else:
                run["last"] = fix["at"]
                run["heard"] = fix["at"]
                run["statuses"].append(fix["status"])
                run["n"] += 1
        else:
            # Between the two thresholds, neither stopped nor under way: hold
            # the current state rather than inventing a transition, but note
            # that she was heard.
            if run is not None:
                run["heard"] = fix["at"]

    if run is not None:
        close(run, None)

    return calls


#: Statuses that mean the vessel is working cargo, in laytime terms.
ALONGSIDE = ("Moored",)

#: Statuses that mean she is waiting.
WAITING = ("At anchor",)


def summarise(calls) -> dict:
    """Totals a laytime conversation actually starts from.

    Three buckets, and they add up to the whole. A stopped vessel often reports
    "Under way using engine" rather than moored or anchored, which is truthful
    AIS: a tug holding station has her engines on and is making no way. Counting
    only moored and anchored would report seven calls and zero hours, so the
    remainder is reported rather than dropped.
    """
    alongside = [c for c in calls if c["status"] in ALONGSIDE]
    waiting = [c for c in calls if c["status"] in WAITING]
    other = [c for c in calls if c["status"] not in ALONGSIDE + WAITING]
    return {
        "calls": len(calls),
        "hours_alongside": round(sum(c["hours"] for c in alongside), 1),
        "hours_at_anchor": round(sum(c["hours"] for c in waiting), 1),
        "hours_otherwise_stopped": round(sum(c["hours"] for c in other), 1),
        "hours_total": round(sum(c["hours"] for c in calls), 1),
        "still_there": any(c["still_there"] for c in calls),
    }
