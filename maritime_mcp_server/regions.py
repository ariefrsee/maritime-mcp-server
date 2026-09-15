"""The sea areas this server can subscribe to, and what each one costs.

Why this module exists at all
-----------------------------

The obvious way to watch more of the world is to widen the bounding box until
it is the world. That does not work on this feed, and the failure is not a
polite error: aisstream accepts the subscription, floods, and then cuts the
connection without a close frame.

Measured on 2026-09-15 from one account, each run a fresh connection:

    subscription            rate      outcome
    Malaysia                0.4/s     stable
    East Asia               3.8/s     stable for 151s
    Southeast Asia          8.0/s     stable for 181s, twice
    US East Coast          10.1/s     stable for 151s
    Mediterranean          25.1/s     stable for 152s
    Europe                 72.2/s     dropped at 126s
    World, two boxes       72.3/s     dropped
    World, one box     78 to 122/s    dropped at 31s, 37s and 51s

So the limit is throughput, not area and not the number of boxes. Several
boxes in one subscription are fine as long as their combined rate stays inside
the budget below. The rate is what has to be rationed, which is why every
region here carries its own measured cost and why the caller is told the total.

A second measured limit rules out the other obvious design. With production
holding one connection, four more were opened and three were refused at the
handshake. One connection per key, near enough, so "a connection per region"
is not available either.
"""

from __future__ import annotations

# The highest sustained message rate observed to survive. Mediterranean ran
# 25.1/s for 152 seconds without dropping; Europe at 72.2/s did not last 130.
# The true cut-off is somewhere between and has not been bisected, so this sits
# at the top of the range actually seen to work rather than at a guess about
# where it fails.
STABLE_BUDGET_PER_S = 25.0

# What a region costs and where it is. `rate_per_s` is the measured message
# rate, `measured_on` the day it was taken. Traffic varies with the hour and
# the season (G15), so these are one observation each, not a constant of
# nature, and the budget has room for that.
#
# Boxes are [[[lat, lon], [lat, lon]]] as the vendor's example shows:
# south-west corner first, then north-east.
REGIONS: dict[str, dict] = {}


def _region(key, title, box, rate_per_s, measured_on, note=None):
    REGIONS[key] = {
        "key": key,
        "title": title,
        "box": box,
        "rate_per_s": rate_per_s,
        "measured_on": measured_on,
        "note": note,
    }


# The table. Rates are filled in from measurement, never from estimate: a
# region whose cost has not been observed carries None and is reported as
# unmeasured rather than being given a plausible looking number (G8).
#
# Eleven regions are still unmeasured, and not for want of trying. A sweep on
# 2026-09-15 measured five of them and was then refused on every subsequent
# connection, each closing inside three seconds with code 1006: the account
# rate-limits new connections after enough of them in a short window. Those
# runs recorded 0.00/s, which is the throttle speaking and not the water, so
# they were discarded rather than written down. An established connection was
# unaffected throughout, which is why set_regions updates the open socket
# instead of reconnecting.
#
# Boxes are deliberately generous at the edges. A region that clips a strait
# in half is worse than one that overlaps its neighbour, because overlap costs
# a little duplicate traffic while a gap loses vessels silently.

_region("malaysia", "Malaysia",
        [[[0.5, 98.5], [7.5, 119.5]]], 0.40, "2026-09-15",
        "The Strait of Malacca, both coasts of the peninsula, Sabah and Sarawak.")
_region("singapore-strait", "Singapore Strait",
        [[[0.7, 103.0], [1.9, 104.9]]], 0.38, "2026-09-15",
        "Almost all of Malaysia's traffic is here: this strip alone measured "
        "0.38/s against 0.40/s for the whole country.")
_region("indonesia", "Indonesia",
        [[[-11.0, 95.0], [6.0, 141.0]]], 3.57, "2026-09-15")
_region("thailand-gulf", "Gulf of Thailand",
        [[[5.0, 99.0], [14.0, 105.0]]], 0.03, "2026-09-15",
        "Barely any receiver coverage: one vessel in 76 seconds.")
_region("vietnam", "Vietnam",
        [[[8.0, 102.0], [22.0, 110.0]]], 0.03, "2026-09-15",
        "Barely any receiver coverage: one vessel in 76 seconds.")
_region("philippines", "Philippines",
        [[[4.0, 116.0], [21.0, 127.0]]], None, None)
_region("china-coast", "China coast",
        [[[18.0, 105.0], [41.0, 125.0]]], None, None)
_region("japan-korea", "Japan and Korea",
        [[[30.0, 125.0], [46.0, 146.0]]], None, None)
_region("india", "India and Bay of Bengal",
        [[[5.0, 65.0], [25.0, 93.0]]], None, None)
_region("arabian-gulf", "Arabian Gulf",
        [[[22.0, 47.0], [31.0, 60.0]]], None, None)
_region("red-sea-suez", "Red Sea and Suez",
        [[[12.0, 32.0], [31.0, 44.0]]], None, None)
_region("mediterranean", "Mediterranean",
        [[[30.0, -6.0], [46.0, 36.0]]], 25.10, "2026-09-15",
        "Held a connection for 152 seconds, the busiest region seen to do so.")
_region("north-sea-baltic", "North Sea and Baltic",
        [[[50.0, -5.0], [66.0, 31.0]]], None, None)
_region("us-east", "US East Coast",
        [[[24.0, -82.0], [45.0, -66.0]]], 10.10, "2026-09-15")
_region("us-west", "US West Coast",
        [[[32.0, -125.0], [49.0, -117.0]]], None, None)
_region("brazil", "Brazil",
        [[[-34.0, -53.0], [0.0, -34.0]]], None, None)
_region("australia", "Australia",
        [[[-44.0, 112.0], [-10.0, 154.0]]], None, None)
_region("west-africa", "West Africa",
        [[[-6.0, -18.0], [15.0, 14.0]]], None, None)


def normalise(value) -> str:
    """One spelling of a region key, used by every entry point that takes one.

    G19: vessels_near_port normalised its input and search_vessels did not, so
    " malaysia " matched nothing while " port klang " worked. Every caller here
    goes through this function so that cannot happen again.
    """
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def parse_keys(value) -> list[str]:
    """Read a comma separated region list into known keys, in order, no repeats."""
    if isinstance(value, (list, tuple)):
        parts = [normalise(v) for v in value]
    else:
        parts = [normalise(p) for p in str(value or "").split(",")]
    seen, out = set(), []
    for part in parts:
        if part and part in REGIONS and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def unknown_keys(value) -> list[str]:
    """The keys a caller asked for that this server does not have.

    Returned so a caller can be told what was dropped rather than silently
    receiving a subscription narrower than the one it asked for.
    """
    if isinstance(value, (list, tuple)):
        parts = [normalise(v) for v in value]
    else:
        parts = [normalise(p) for p in str(value or "").split(",")]
    return [p for p in parts if p and p not in REGIONS]


def boxes_for(keys) -> list:
    """The bounding boxes for a set of regions, as one subscription payload."""
    return [box for key in parse_keys(keys) for box in REGIONS[key]["box"]]


def unmeasured(keys) -> list[str]:
    """Selected regions whose cost has never been observed."""
    return [k for k in parse_keys(keys) if REGIONS[k]["rate_per_s"] is None]


def rate_for(keys):
    """Combined measured rate, or None if any selected region is unmeasured.

    Overlapping regions are added together, which over-counts the shared water.
    That errs towards a selection that stays connected rather than one that
    drops, which is the right direction to be wrong in.

    None rather than a partial sum: a total that quietly omits the one region
    nobody has measured is exactly the plausible looking number G8 exists to
    stop, and it would be lowest precisely when the unmeasured region is
    busiest.
    """
    chosen = parse_keys(keys)
    if any(REGIONS[k]["rate_per_s"] is None for k in chosen):
        return None
    return round(sum(REGIONS[k]["rate_per_s"] for k in chosen), 2)


def within_budget(keys) -> bool | None:
    """True, False, or None when the cost of the selection is not known."""
    rate = rate_for(keys)
    return None if rate is None else rate <= STABLE_BUDGET_PER_S


def describe(keys=()) -> dict:
    """The region table plus what the given selection costs, for a client to
    render a picker against. Everything a caller needs to make the trade-off
    is here, including the evidence behind the budget."""
    selected = parse_keys(keys)
    return {
        "budget_per_s": STABLE_BUDGET_PER_S,
        "budget_basis": (
            "Highest rate observed to hold a connection. 25.1/s ran 152s; "
            "72.2/s dropped at 126s; a whole-world box dropped inside a minute "
            "on three attempts. Measured 2026-09-15, one account, one run each."
        ),
        "selected": selected,
        "selected_rate_per_s": rate_for(selected),
        "within_budget": within_budget(selected),
        "unmeasured": unmeasured(selected),
        "regions": [
            {k: v for k, v in region.items() if k != "box"} | {"bounds": bounds_of(region["box"])}
            for region in REGIONS.values()
        ],
    }


def bounds_of(box) -> dict:
    """The outer extent of a region's boxes, for a client that wants to frame a
    map on it. Reported as plain named edges rather than the vendor's nested
    pairs, because a client should not have to know the wire format."""
    lats = [corner[0] for pair in box for corner in pair]
    lons = [corner[1] for pair in box for corner in pair]
    return {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)}


def contains(key, lat, lon) -> bool:
    """Whether a position falls inside a region. Used to filter what is already
    in the store, which is a different question from what is subscribed to: the
    store keeps whatever arrived, including from a region since deselected."""
    region = REGIONS.get(normalise(key))
    if region is None or lat is None or lon is None:
        return False
    for (south, west), (north, east) in region["box"]:
        if south <= lat <= north and west <= lon <= east:
            return True
    return False
