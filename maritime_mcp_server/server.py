"""Maritime vessel data — Model Context Protocol (MCP) server.

Exposes the vessel dataset as MCP tools over stdio, so any MCP-compatible client
(Claude Desktop, an agent framework, an IDE) can query live vessel data through
a standard protocol instead of a bespoke integration. This is the same tool
surface used by the companion `maritime-vessel-agent` project, published here as
a reusable MCP server.

Run:
    python -m maritime_mcp_server.server    # stdio transport (for MCP clients)

Targets the mcp 2.x MCPServer API. Version 1.x called this class FastMCP and
served it from mcp.server.fastmcp.

Wire into Claude Desktop by adding this server to claude_desktop_config.json —
see the README.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .collector import Collector
from .history import VesselHistory
from .store import VesselStore
from . import regions as regions_module
from . import port_calls as port_calls_module
from . import anchorages as anchorages_module

DATA_FILE = files(__package__).joinpath("data/vessels.json")

# Malaysian commercial ports. The list was peninsular only, which meant a vessel
# off Kota Kinabalu took the nearest name it could find and was labelled Tanjung
# Pelepas from 800 nm away. Naming a port a vessel is nowhere near is the bug
# S06 fixed at 38 nm; the list has to reach wherever the bounding box does.
PORT_COORDS = {
    # Peninsular, west coast
    "port klang": (3.00, 101.36),
    "penang": (5.41, 100.34),
    "langkawi": (6.32, 99.85),
    "malacca": (2.19, 102.25),
    "port dickson": (2.52, 101.80),
    "lumut": (4.24, 100.63),
    # Peninsular, south and east coast
    "tanjung pelepas": (1.36, 103.54),
    "pasir gudang": (1.44, 103.90),
    "kuantan": (3.97, 103.43),
    "kemaman": (4.25, 103.45),
    "kuala terengganu": (5.33, 103.14),
    "kota bharu": (6.20, 102.28),
    # Sarawak
    "kuching": (1.57, 110.34),
    "bintulu": (3.26, 113.06),
    "miri": (4.40, 113.99),
    "sibu": (2.29, 111.83),
    # Sabah and Labuan
    "labuan": (5.28, 115.24),
    "kota kinabalu": (5.98, 116.07),
    "sandakan": (5.84, 118.12),
    "tawau": (4.24, 117.89),
}

@asynccontextmanager
async def _lifespan(_server):
    """Run the AIS collector for as long as the server is up.

    Without an API key the collector declines to start and the server answers
    from its bundled snapshot, which is a supported mode rather than a failure.
    """
    history = VesselHistory()
    store = VesselStore(history=history)
    collector = Collector(store)
    started = collector.start()
    set_history(history)
    set_collector(collector if started else None)
    if started:
        set_store(store)
    try:
        yield {"store": store, "collector": collector}
    finally:
        await collector.stop()
        set_store(None)
        set_collector(None)
        set_history(None)
        history.close()


def _own_version() -> str:
    """This server's version, for the serverInfo a client sees on connect.

    Under mcp 1.x this field reported the SDK's version, which was misleading.
    Under 2.x it defaults to an empty string. Reporting the package's own version
    is correct for the first time, but the lookup raises when the package is not
    installed, which happens when running from a source checkout.
    """
    try:
        return version("maritime-mcp-server")
    except PackageNotFoundError:
        return "0.0.0+source"


mcp = MCPServer("maritime-vessel-data", version=_own_version(), lifespan=_lifespan)


SNAPSHOT_DATE = "2026-07-20"

# The live store is filled by the collector, which arrives in S03. Until then
# this stays None and every answer comes from the bundled snapshot.
_store = None


def set_store(store) -> None:
    """Register the live vessel store. Called by the server lifespan hook."""
    global _store
    _store = store


_history = None


def set_history(history) -> None:
    """Register the durable history. Called by the server lifespan hook."""
    global _history
    _history = history


_collector = None


def set_collector(collector) -> None:
    """Register the running collector, so the region tools can reach it.

    None when there is no API key and the server is answering from the bundled
    snapshot. The region tools report that state rather than pretending a
    subscription exists to change.
    """
    global _collector
    _collector = collector


@lru_cache(maxsize=1)
def _load_snapshot() -> list[dict]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


# Responses are read by a model, not a person. Indentation cost 29 percent of a
# typical payload and carried no information, so everything is serialised
# compactly through one function rather than each tool choosing for itself.
def _respond(payload) -> str:
    return json.dumps(payload, separators=(",", ":"))


# AIS positions are nowhere near as precise as a Python float prints them.
# Four decimal places is roughly 11 metres, which is finer than the source.
# The extra digits were noise that looked like data.
_PRECISION = {"lat": 4, "lon": 4, "speed_knots": 1, "distance_nm": 1, "length_m": 0}


def _tidy(record: dict, drop=()) -> dict:
    """Round the numbers and drop fields that carry nothing in this context.

    Nothing is removed for being unknown: a null still means AIS has not
    reported that field, which is a different claim from the field being
    absent. Only genuinely redundant fields are dropped, and only when the
    caller already has the information.
    """
    out = {}
    for key, value in record.items():
        if key in drop:
            continue
        places = _PRECISION.get(key)
        if places is not None and isinstance(value, (int, float)):
            value = round(value, places)
            if places == 0:
                value = int(value)
        out[key] = value
    return out


def _filter_text(value) -> str:
    """Normalise a filter the way the port lookup already normalises a port name.

    A filter of only whitespace means the same as no filter. Before this, a
    stray space made a filter match nothing, which returned a confidently wrong
    answer rather than an error.
    """
    return value.strip().lower() if isinstance(value, str) else ""


def _nearest_port(lat, lon) -> tuple[str | None, float | None]:
    """Closest port from the known list, and how far away it is in nautical miles.

    AIS does not transmit either value; both are computed here. The distance is
    returned with the name because the name alone reads as "at this port", and
    the list holds five ports spread along the whole coast. Measured against a
    live feed of 230 vessels, the median vessel was 19.5 nm from the port it was
    labelled with and the furthest was 37.9 nm. Naming a port without saying how
    far it is presents a derived value as if it were an observation (G8).

    No cutoff is applied. Any threshold would be arbitrary, and discarding the
    name loses information the caller may want; reporting the distance lets the
    caller decide what counts as near.
    """
    if lat is None or lon is None:
        return None, None
    best, best_dist = None, None
    for name, (plat, plon) in PORT_COORDS.items():
        dist = _haversine_nm(plat, plon, lat, lon)
        if best_dist is None or dist < best_dist:
            best, best_dist = name, dist
    if best is None:
        return None, None
    return best.title(), round(best_dist, 1)


def get_vessels(require_position: bool = True) -> tuple[list[dict], dict]:
    """Every vessel currently known, plus where the data came from.

    Prefers the live store when it holds anything, and falls back to the bundled
    snapshot otherwise. The provenance is returned alongside rather than being
    left implicit, because a snapshot position presented as a live one is worse
    than no answer at all.
    """
    if _store is not None:
        records = _store.records(require_position=require_position)
        if records:
            # AIS does not transmit a nearest port, so it is derived here rather
            # than in the mapping layer, which has no knowledge of our port list.
            for r in records:
                port, distance_nm = _nearest_port(r.get("lat"), r.get("lon"))
                r["nearest_port"] = port
                r["nearest_port_nm"] = distance_nm
            ages = [r.get("position_age_seconds") for r in records
                    if r.get("position_age_seconds") is not None]
            return records, {
                "source": "live",
                "vessel_count": len(records),
                "oldest_position_age_seconds": max(ages) if ages else None,
            }
    # The snapshot carries a curated nearest_port but no distance. Deriving
    # both here keeps one code path, so a snapshot record and a live record
    # answer the same questions in the same shape.
    snapshot = []
    for r in _load_snapshot():
        record = dict(r)
        port, distance_nm = _nearest_port(record.get("lat"), record.get("lon"))
        record["nearest_port"] = port
        record["nearest_port_nm"] = distance_nm
        snapshot.append(record)

    return snapshot, {
        "source": "snapshot",
        "vessel_count": len(snapshot),
        "snapshot_date": SNAPSHOT_DATE,
        "note": (
            "Live AIS is unavailable, so this is the bundled sample dataset. "
            "Positions are fixed and do not reflect where these vessels are now."
        ),
    }


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    radius_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return radius_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@mcp.tool()
def search_vessels(
    vessel_type: Annotated[str, Field(
        description="Ship category to match, case insensitive and partial. "
                    "Examples: Tanker, Cargo, Passenger, Tug, Fishing. "
                    "Leave blank to match any type.")] = "",
    flag: Annotated[str, Field(
        description="Flag state to match, case insensitive and partial, for "
                    "example Malaysia or Singapore. Leave blank to match any flag.")] = "",
    status: Annotated[str, Field(
        description="Navigational status to match, case insensitive and partial. "
                    "Examples: Under way, At anchor, Moored. "
                    "Leave blank to match any status.")] = "",
    limit: Annotated[int, Field(
        gt=0, le=200,
        description="Maximum number of vessels to return, between 1 and 200. "
                    "The response always reports how many matched, so a "
                    "truncated answer is visible rather than silent.")] = 25,
) -> str:
    """Search the vessel dataset by type, flag state, and/or navigational status.

    Any argument left blank is ignored, and surrounding whitespace is ignored.
    Returns JSON with a "data" block stating the source, a "matches" count of
    everything that matched, a "returned" count of how many are included, and a
    "vessels" list. When returned is less than matches the list was capped by
    the limit argument: raise it or narrow the search to see the rest. When data.source is "snapshot" the positions are from a
    fixed sample dataset and are not current: say so when answering.
    Fields that AIS has not reported yet are null, never guessed.
    """
    wanted_type = _filter_text(vessel_type)
    wanted_flag = _filter_text(flag)
    wanted_status = _filter_text(status)

    vessels, provenance = get_vessels()
    results = []
    for v in vessels:
        if wanted_type and wanted_type not in (v.get("type") or "").lower():
            continue
        if wanted_flag and wanted_flag not in (v.get("flag") or "").lower():
            continue
        if wanted_status and wanted_status not in (v.get("status") or "").lower():
            continue
        results.append(v)
    shown = [_tidy(v) for v in results[:limit]]
    return _respond({"data": provenance, "matches": len(results),
                     "returned": len(shown), "vessels": shown})


@mcp.tool()
def vessels_near_port(
    port: Annotated[str, Field(
        description="Port name. One of: Port Klang, Tanjung Pelepas, Penang, "
                    "Malacca, Langkawi. Case insensitive.")],
    radius_nm: Annotated[float, Field(
        gt=0, le=500,
        description="Search radius in nautical miles, greater than 0 and at most "
                    "500. The server only receives traffic for Malaysian waters, "
                    "so a radius beyond that covers sea it never sees.")] = 30.0,
    limit: Annotated[int, Field(
        gt=0, le=200,
        description="Maximum number of vessels to return, nearest first, between 1 and 200. "
                    "The response always reports how many matched, so a "
                    "truncated answer is visible rather than silent.")] = 25,
) -> str:
    """List vessels within a radius (nautical miles) of a named port.

    Recognized ports: Port Klang, Tanjung Pelepas, Penang, Malacca, Langkawi.
    Returns JSON with a "data" block stating the source, a "matches" count of
    everything inside the radius, a "returned" count of how many are included,
    and a "vessels" list annotated with distance_nm, nearest first. When
    returned is less than matches the nearest were kept and the rest omitted. When data.source is "snapshot"
    the positions are not current: say so when answering.
    """
    key = port.strip().lower()
    if key not in PORT_COORDS:
        return json.dumps(
            {"error": f"Unknown port '{port}'. Known ports: {', '.join(PORT_COORDS)}"}
        )
    plat, plon = PORT_COORDS[key]
    vessels, provenance = get_vessels()
    hits = []
    for v in vessels:
        if v.get("lat") is None or v.get("lon") is None:
            continue
        dist = _haversine_nm(plat, plon, v["lat"], v["lon"])
        if dist <= radius_nm:
            hits.append({**v, "distance_nm": round(dist, 1)})
    hits.sort(key=lambda x: x["distance_nm"])
    # The caller named the port, so repeating it on every vessel tells them
    # nothing. The per vessel age is already summarised in the provenance block.
    shown = [_tidy(v, drop=("nearest_port", "position_age_seconds")) for v in hits[:limit]]
    return _respond({"data": provenance, "port": port, "radius_nm": radius_nm,
                     "matches": len(hits), "returned": len(shown), "vessels": shown})


@mcp.tool()
def vessel_details(
    query: Annotated[str, Field(
        description="A nine digit MMSI for an exact match, or part of a ship's "
                    "name for a partial one. Must not be blank.")],
) -> str:
    """Look up a single vessel by exact MMSI or by (partial) name.

    Returns JSON with a "data" block stating the source and a "vessel" record,
    or an error object if no unique match is found. When data.source is
    "snapshot" the position is not current. Null fields mean AIS has not
    reported that detail, not that the value is zero or unknown to the vessel.
    """
    q = query.strip().lower()
    if not q:
        _, provenance = get_vessels(require_position=False)
        return _respond({
            "data": provenance,
            "error": "A vessel name or MMSI is required. Pass part of a ship's "
                     "name, or its nine digit MMSI.",
        })
    # A details lookup does not need a position, and AIS often gives a vessel's
    # identity before it gives its whereabouts.
    vessels, provenance = get_vessels(require_position=False)
    matches = [v for v in vessels
               if q == (v.get("mmsi") or "") or q in (v.get("name") or "").lower()]
    if not matches:
        return _respond({"data": provenance,
                         "error": f"No vessel found matching '{query}'."})
    if len(matches) > 1:
        return _respond({
            "data": provenance,
            "error": f"'{query}' matched {len(matches)} vessels; be more specific.",
            "candidates": [{"mmsi": m.get("mmsi"), "name": m.get("name")} for m in matches],
        })
    return _respond({"data": provenance, "vessel": _tidy(matches[0])})


@mcp.tool()
def vessel_track(
    query: Annotated[str, Field(
        description="Vessel to track, by exact MMSI or by (partial) name, "
                    "case insensitive.")],
    hours: Annotated[float, Field(
        gt=0, le=24 * 90,
        description="How far back to look, in hours, up to the retention "
                    "window of 90 days. History exists only from the point "
                    "this server started keeping it.")] = 6,
) -> str:
    """Where a vessel has been over the last few hours.

    Returns JSON with a "data" block and a "track" list of positions, oldest
    first. Each position is one AIS report that was actually received: the gaps
    between them are real, and nothing is interpolated to fill them.

    History only exists from the point this server started keeping it. An empty
    track means nothing was heard, not that the vessel did not move.
    """
    if _history is None:
        return _respond({
            "data": {"source": "unavailable"},
            "error": "History is not enabled on this server.",
            "track": [],
        })

    hours = max(0.0, min(float(hours), 24 * 90))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Resolve a name to an MMSI through the same lookup the other tools use, so
    # "track the Kowloon Express" behaves like "find the Kowloon Express".
    q = query.strip()
    mmsi = q if q.isdigit() else None
    if mmsi is None:
        vessels, _ = get_vessels(require_position=False)
        matches = [v for v in vessels if q.lower() in (v.get("name") or "").lower()]
        if not matches:
            return _respond({
                "data": {"source": "history"},
                "error": f"No vessel found matching '{query}'.",
                "track": [],
            })
        if len(matches) > 1:
            return _respond({
                "data": {"source": "history"},
                "error": f"'{query}' matched {len(matches)} vessels; be more specific.",
                "candidates": [{"mmsi": m.get("mmsi"), "name": m.get("name")} for m in matches],
                "track": [],
            })
        mmsi = matches[0].get("mmsi")

    track = _history.track(mmsi, since)
    return _respond({
        "data": {
            "source": "history",
            "mmsi": mmsi,
            "hours": hours,
            "position_count": len(track),
            "note": (
                "Positions are AIS reports as received. Gaps are real and "
                "nothing between them is interpolated."
            ),
        },
        "track": track,
    })


@mcp.tool()
def fleet_track(
    hours: Annotated[float, Field(
        gt=0, le=24 * 90,
        description="How far back to look, in hours. A wider window returns "
                    "proportionally more, so narrow it rather than raising "
                    "the limit.")] = 3,
    limit: Annotated[int, Field(
        gt=0, le=200_000,
        description="Maximum positions to return across the whole fleet. When "
                    "the cap is reached the response says so, rather than "
                    "quietly returning less than was asked for.")] = 20000,
) -> str:
    """Where every vessel has been over the last few hours.

    Returns JSON with a "data" block and a "fleet" list, one entry per vessel,
    each with its identity and its positions oldest first. Intended for playback
    and for checking work against what was actually observed.

    Each position is one AIS report that was received. The gaps between them are
    real: the median vessel reports only a handful of times an hour, so two fixes
    an hour apart are two observations and not a path. Nothing is interpolated.

    When "truncated" is true the row cap was reached and this is not the whole
    picture. Narrow the window rather than assuming the missing vessels are gone.
    """
    if _history is None:
        return _respond({
            "data": {"source": "unavailable"},
            "error": "History is not enabled on this server.",
            "fleet": [],
        })

    retention_hours = _history.retention.total_seconds() / 3600
    hours = max(0.0, min(float(hours), retention_hours))
    limit = max(1, min(int(limit), 200_000))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    fleet, truncated = _history.fleet_track(since, limit)
    positions = sum(len(v["positions"]) for v in fleet.values())

    return _respond({
        "data": {
            "source": "history",
            "hours": hours,
            "vessel_count": len(fleet),
            "position_count": positions,
            "truncated": truncated,
            "row_limit": limit,
            "note": (
                "Positions are AIS reports as received. Gaps are real and "
                "nothing between them is interpolated."
            ),
        },
        "fleet": list(fleet.values()),
    })


@mcp.tool()
def list_regions() -> str:
    """List the sea areas this server can watch, and what each one costs.

    The feed is rationed by throughput rather than by area. A subscription
    above roughly 25 messages a second is closed by the vendor within a couple
    of minutes, and a whole-world subscription dies inside one, so a selection
    has to be chosen to fit a budget rather than simply widened.

    Each region reports its measured message rate. A rate of null means nobody
    has measured that region yet, and a selection containing one has an unknown
    total: that is reported as unknown rather than as a partial sum. Use
    set_regions to change what is being watched.
    """
    active = _collector.regions if _collector is not None else []
    payload = regions_module.describe(active)
    payload["active"] = active
    payload["live"] = _collector is not None
    if _collector is None:
        payload["note"] = (
            "No live subscription: the server has no AIS key and is answering "
            "from its bundled snapshot. The region table is still accurate, but "
            "nothing is being watched and set_regions has nothing to change."
        )
    return _respond(payload)


@mcp.tool()
async def set_regions(
    region_keys: Annotated[str, Field(
        description="Comma separated region keys to watch, for example "
                    "'malaysia,singapore-strait'. Call list_regions for the "
                    "available keys and what each one costs.")],
) -> str:
    """Change which sea areas the live subscription watches.

    Applied to the open connection where possible, so the feed is not
    interrupted. Vessels already collected are not discarded: the store keeps
    them until they age out of its 30-minute window, so a region just switched
    away from fades rather than vanishing.

    A selection over the throughput budget is accepted and reported, not
    refused. The caller asked for it, and the honest answer is that the feed
    will drop and reconnect repeatedly rather than a limit that does not exist.
    """
    if _collector is None:
        return _respond({
            "ok": False,
            "error": "There is no live subscription to change. The server has no "
                     "AIS key and is answering from its bundled snapshot.",
            "regions": [],
        })
    result = await _collector.set_regions(region_keys)
    if result.get("ok") and result.get("within_budget") is False:
        result["warning"] = (
            f"This selection is about {result['estimated_rate_per_s']} messages a "
            f"second, over the {result['budget_per_s']} the feed has been seen to "
            "sustain. Expect it to drop and reconnect, losing positions each time."
        )
    if result.get("ok") and result.get("within_budget") is None:
        result["warning"] = (
            "Part of this selection has never been measured, so its cost is "
            "unknown. It may or may not stay connected."
        )
    return _respond(result)


def _parse_bbox(text):
    """Read "south,west,north,east" into floats, or return None with a reason."""
    parts = [p.strip() for p in str(text or "").split(",") if p.strip()]
    if len(parts) != 4:
        return None, "A bbox is four numbers: south,west,north,east."
    try:
        south, west, north, east = (float(p) for p in parts)
    except ValueError:
        return None, "A bbox is four numbers: south,west,north,east."
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        return None, "Latitudes must be between -90 and 90."
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        return None, "Longitudes must be between -180 and 180."
    if south > north:
        return None, "South must not be north of north."
    return (south, west, north, east), None


@mcp.tool()
def vessels_in_area(
    bbox: Annotated[str, Field(
        description="Area to report, as 'south,west,north,east' in degrees, for "
                    "example '1.0,103.0,2.0,104.5'. Leave blank to use region "
                    "instead.")] = "",
    region: Annotated[str, Field(
        description="A region key to report instead of a bbox, for example "
                    "'malaysia'. Call list_regions for the available keys. "
                    "Ignored when bbox is given.")] = "",
    limit: Annotated[int, Field(
        gt=0, le=500,
        description="Maximum vessels to return, between 1 and 500. The response "
                    "always states how many were in the area, so a truncated "
                    "answer is visible rather than silent.")] = 200,
) -> str:
    """Vessels inside one area of sea, rather than everywhere the server watches.

    This exists because a selection covering several regions can hold far more
    vessels than any one caller wants at once, and sending all of them is
    expensive for an answer about one strait. Ask for the water you care about.

    The area filters what has already been collected, which is a different
    question from what is subscribed to: a region switched away from still has
    vessels in the store until they age out, and an area nobody is subscribed
    to simply returns nothing.
    """
    if bbox.strip():
        parsed, error = _parse_bbox(bbox)
        if error:
            return _respond({"error": error, "matches": 0, "returned": 0, "vessels": []})
        south, west, north, east = parsed

        def inside(v):
            lat, lon = v.get("lat"), v.get("lon")
            if lat is None or lon is None:
                return False
            # A box crossing the antimeridian has west greater than east, and
            # the longitude test has to wrap with it rather than matching
            # nothing, which is what a plain range comparison would do.
            if west <= east:
                in_lon = west <= lon <= east
            else:
                in_lon = lon >= west or lon <= east
            return south <= lat <= north and in_lon
        area = {"bbox": {"south": south, "west": west, "north": north, "east": east}}
    elif region.strip():
        key = regions_module.normalise(region)
        if key not in regions_module.REGIONS:
            return _respond({
                "error": f"No region called {region.strip()!r}. Call list_regions "
                         "for the available keys.",
                "matches": 0, "returned": 0, "vessels": [],
            })

        def inside(v):
            return regions_module.contains(key, v.get("lat"), v.get("lon"))
        area = {"region": key, "bounds": regions_module.bounds_of(
            regions_module.REGIONS[key]["box"])}
    else:
        return _respond({
            "error": "Give either a bbox or a region.",
            "matches": 0, "returned": 0, "vessels": [],
        })

    vessels, provenance = get_vessels()
    matched = [v for v in vessels if inside(v)]
    shown = [_tidy(v) for v in matched[:limit]]
    return _respond({"data": provenance, "area": area, "matches": len(matched),
                     "returned": len(shown), "vessels": shown})


@mcp.tool()
def vessels_watched(
    limit: Annotated[int, Field(
        gt=0, le=1000,
        description="Maximum vessels to return, between 1 and 1000. The response "
                    "always states how many were in the watched regions, so a "
                    "truncated answer is visible rather than silent.")] = 500,
) -> str:
    """Vessels inside the regions currently being watched, and nothing else.

    The store keeps every vessel it has collected until the position ages out
    of the thirty minute window, which includes vessels from a region that has
    since been deselected. That is the right thing for the store to do and the
    wrong thing to show: someone who selects Malaysia means show me Malaysia,
    not Malaysia plus whatever was on screen ten minutes ago.

    With no live subscription there is nothing being watched, so no filter
    applies and everything is returned with a note saying so.
    """
    vessels, provenance = get_vessels()
    active = _collector.regions if _collector is not None else []

    if not active:
        return _respond({
            "data": provenance,
            "watching": [],
            "note": "Nothing is being watched, so nothing is filtered out. The "
                    "server has no live subscription and is answering from its "
                    "bundled snapshot.",
            "matches": len(vessels),
            "returned": len(vessels[:limit]),
            "vessels": [_tidy(v) for v in vessels[:limit]],
        })

    matched = [
        v for v in vessels
        if any(regions_module.contains(key, v.get("lat"), v.get("lon")) for key in active)
    ]

    # Recomputed over what is actually being returned. The provenance from
    # get_vessels reports the stalest position in the whole store, and a caller
    # told "the oldest fix here is 29 minutes" about a vessel that has been
    # filtered out is being told something false about the answer it received.
    ages = [v.get("position_age_seconds") for v in matched
            if v.get("position_age_seconds") is not None]
    reported = dict(provenance)
    reported["vessel_count"] = len(matched)
    reported["oldest_position_age_seconds"] = max(ages) if ages else None

    shown = [_tidy(v) for v in matched[:limit]]
    return _respond({"data": reported, "watching": active, "matches": len(matched),
                     "returned": len(shown), "vessels": shown})


def _resolve_vessel(query):
    """One MMSI from a query, or an error payload. Shared so that "track the
    Kowloon Express" and "port calls for the Kowloon Express" resolve the same
    name the same way."""
    q = str(query).strip()
    if q.isdigit():
        return q, None
    vessels, _ = get_vessels(require_position=False)
    matches = [v for v in vessels if q.lower() in (v.get("name") or "").lower()]
    if not matches:
        return None, {"error": f"No vessel found matching '{query}'."}
    if len(matches) > 1:
        return None, {
            "error": f"'{query}' matched {len(matches)} vessels; be more specific.",
            "candidates": [{"mmsi": m.get("mmsi"), "name": m.get("name")} for m in matches],
        }
    return matches[0].get("mmsi"), None


@mcp.tool()
def port_calls(
    query: Annotated[str, Field(
        description="Vessel to report, by exact MMSI or by (partial) name, "
                    "case insensitive.")],
    days: Annotated[float, Field(
        gt=0, le=90,
        description="How far back to look, in days, up to the 90 day retention "
                    "window. History exists only from the point this server "
                    "started keeping it.")] = 7,
) -> str:
    """When a vessel stopped, where, for how long, and whether she was working.

    This is the skeleton of a Statement of Facts, read out of the recorded
    track rather than typed from memory: arrival, time alongside or at anchor,
    departure. Anchored and moored are kept apart, because in laytime terms one
    is waiting and the other is working.

    Everything reported was observed. A vessel that has not been seen to leave
    has no departure time rather than an assumed one; a stop spanning a hole in
    coverage is cut at the hole rather than claimed as continuous; and a stop
    far from any known port is reported as at sea rather than given the name of
    the nearest one. Where an arrival was not witnessed, because the record
    starts mid-stop or follows a coverage hole, arrival_observed is false and
    the arrival time is only when this server first saw her there.
    """
    if _history is None:
        return _respond({"data": {"source": "unavailable"},
                         "error": "History is not enabled on this server.",
                         "calls": []})

    mmsi, problem = _resolve_vessel(query)
    if problem:
        return _respond({"data": {"source": "history"}, **problem, "calls": []})

    days = max(0.0, min(float(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    track = _history.track(mmsi, since)

    fixes = [{"observed_at": p.get("observed_at"), "lat": p.get("lat"),
              "lon": p.get("lon"), "sog": p.get("speed_knots"),
              "status": p.get("status")} for p in track]
    found = port_calls_module.find_calls(fixes, _nearest_port)

    return _respond({
        "data": {
            "source": "history",
            "mmsi": mmsi,
            "days": days,
            "position_count": len(track),
            "note": (
                "Reconstructed from recorded positions. A vessel is stopped "
                "below 0.5 knots and under way above 3. Stops shorter than 45 "
                "minutes are not reported as calls, and a gap in coverage of "
                "over an hour ends a stop rather than being spanned."
            ),
        },
        "summary": port_calls_module.summarise(found),
        "calls": found,
    })


@mcp.tool()
def congestion(
    region: Annotated[str, Field(
        description="Region key to report, for example 'malacca-strait'. Call "
                    "list_regions for the keys. Ignored when bbox is given.")] = "",
    bbox: Annotated[str, Field(
        description="Area to report instead, as 'south,west,north,east' in "
                    "degrees.")] = "",
    hours: Annotated[int, Field(
        gt=0, le=24 * 14,
        description="How far back to look, in hours, up to two weeks.")] = 48,
) -> str:
    """How busy an area has been, hour by hour, from the recorded track.

    Counts distinct vessels per hour by what they were reporting: at anchor,
    moored, or under way. The anchored count is the one that answers "how long
    is the queue", which is what a charterer rings an agent about.

    Each vessel is counted once per hour it was heard in, so a vessel reporting
    twenty times in an hour counts once. An hour with no coverage reads as zero
    and is indistinguishable from an hour with no ships, which is why the
    response reports how many positions each hour was built from.
    """
    if _history is None:
        return _respond({"data": {"source": "unavailable"},
                         "error": "History is not enabled on this server.",
                         "hours": []})

    if bbox.strip():
        parsed, error = _parse_bbox(bbox)
        if error:
            return _respond({"error": error, "hours": []})
        south, west, north, east = parsed
        area = {"bbox": {"south": south, "west": west, "north": north, "east": east}}
    elif region.strip():
        key = regions_module.normalise(region)
        if key not in regions_module.REGIONS:
            return _respond({
                "error": f"No region called {region.strip()!r}. Call list_regions "
                         "for the available keys.",
                "hours": [],
            })
        bounds = regions_module.bounds_of(regions_module.REGIONS[key]["box"])
        south, west = bounds["south"], bounds["west"]
        north, east = bounds["north"], bounds["east"]
        area = {"region": key, "bounds": bounds}
    else:
        return _respond({"error": "Give either a region or a bbox.", "hours": []})

    hours = max(1, min(int(hours), 24 * 14))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    counted = _history.activity_by_hour(since, south, west, north, east)

    anchored = [h["at_anchor"] for h in counted]
    return _respond({
        "data": {
            "source": "history",
            "hours": hours,
            "note": (
                "Distinct vessels per hour, by reported status. An hour with no "
                "coverage reads as zero and cannot be told apart from an hour "
                "with no ships, so positions is given alongside each count."
            ),
        },
        "area": area,
        "summary": {
            "hours_covered": len(counted),
            "at_anchor_now": anchored[-1] if anchored else None,
            "at_anchor_median": (sorted(anchored)[len(anchored) // 2] if anchored else None),
            "at_anchor_peak": max(anchored) if anchored else None,
        },
        "hours": counted,
    })


#: Grid resolution for the density map, in degrees. About 1.2 nautical miles,
#: which resolves an anchorage from the lane beside it while keeping the answer
#: to roughly nine thousand cells over the Malacca Strait. Measured: 0.005 deg
#: gives 33,000 cells and 670 KB, which is more than a browser wants for a
#: background layer.
DEFAULT_DENSITY_CELL = 0.02


@mcp.tool()
def traffic_density(
    region: Annotated[str, Field(
        description="Region key to report, for example 'malacca-strait'. Call "
                    "list_regions for the keys. Ignored when bbox is given.")] = "",
    bbox: Annotated[str, Field(
        description="Area to report instead, as 'south,west,north,east'.")] = "",
    days: Annotated[float, Field(
        gt=0, le=90,
        description="How far back to include, in days, up to the 90 day "
                    "retention window.")] = 7,
    cell_degrees: Annotated[float, Field(
        gt=0.001, le=1.0,
        description="Grid cell size in degrees. 0.02 is about 1.2 nautical "
                    "miles. Smaller resolves more and costs more.")] = DEFAULT_DENSITY_CELL,
) -> str:
    """Where vessels have actually been, as a grid of counts.

    Read this as coverage as much as traffic. It shows where positions were
    *received*, so an empty cell means either that no ship went there or that
    nothing was listening. Port Klang reads as empty on this map and it is one
    of the busiest ports in the world.

    Each cell reports distinct vessels and total positions separately, because
    they answer different questions: one ship anchored for two days makes
    hundreds of positions in a single cell, which is a fact about that ship and
    not about how busy the cell is.
    """
    if _history is None:
        return _respond({"data": {"source": "unavailable"},
                         "error": "History is not enabled on this server.",
                         "cells": []})

    if bbox.strip():
        parsed, error = _parse_bbox(bbox)
        if error:
            return _respond({"error": error, "cells": []})
        south, west, north, east = parsed
        area = {"bbox": {"south": south, "west": west, "north": north, "east": east}}
    elif region.strip():
        key = regions_module.normalise(region)
        if key not in regions_module.REGIONS:
            return _respond({
                "error": f"No region called {region.strip()!r}. Call list_regions "
                         "for the available keys.",
                "cells": [],
            })
        bounds = regions_module.bounds_of(regions_module.REGIONS[key]["box"])
        south, west = bounds["south"], bounds["west"]
        north, east = bounds["north"], bounds["east"]
        area = {"region": key, "bounds": bounds}
    else:
        return _respond({"error": "Give either a region or a bbox.", "cells": []})

    days = max(0.0, min(float(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cells = _history.density(since, south, west, north, east, float(cell_degrees))

    return _respond({
        "data": {
            "source": "history",
            "days": days,
            "cell_degrees": cell_degrees,
            "cell_count": len(cells),
            "note": (
                "Where positions were received, which is traffic and receiver "
                "coverage combined. An empty cell means no ship went there or "
                "nothing was listening, and this data cannot tell them apart."
            ),
        },
        "area": area,
        # Tuples rather than objects: nine thousand cells of {"lat":...} is
        # mostly key names, and the order is documented here instead.
        "fields": ["lat", "lon", "vessels", "positions"],
        "cells": cells,
    })


#: Grid used to find anchorages. Finer than the traffic map, because two
#: anchorages a mile apart are two places and 0.02 degrees would merge them.
ANCHORAGE_CELL = 0.01


@mcp.tool()
def anchorages(
    region: Annotated[str, Field(
        description="Region key to search, for example 'malacca-strait'. Call "
                    "list_regions for the keys. Ignored when bbox is given.")] = "",
    bbox: Annotated[str, Field(
        description="Area to search instead, as 'south,west,north,east'.")] = "",
    days: Annotated[float, Field(
        gt=0, le=90,
        description="How far back to include, in days.")] = 7,
) -> str:
    """Where vessels actually anchor, found in the recorded positions.

    No chart is consulted. This looks for water where a lot of vessels reported
    "At anchor" and groups the touching parts into one place, so what comes back
    is where ships really wait rather than where they are permitted to. For a
    question about queueing, the first is the useful one.

    Nothing is named. The cluster off eastern Singapore is obviously the eastern
    anchorage to anyone who works there, but AIS does not say so and this will
    not invent it. Each is given its extent, not a radius: an anchorage is
    usually a long thin thing along a coast and a circle would claim water
    nobody anchors in.

    Bear the coverage caveat in mind. An anchorage nothing is listening to does
    not appear here, and that is not the same as an anchorage nobody uses.
    """
    if _history is None:
        return _respond({"data": {"source": "unavailable"},
                         "error": "History is not enabled on this server.",
                         "anchorages": []})

    if bbox.strip():
        parsed, error = _parse_bbox(bbox)
        if error:
            return _respond({"error": error, "anchorages": []})
        south, west, north, east = parsed
        area = {"bbox": {"south": south, "west": west, "north": north, "east": east}}
    elif region.strip():
        key = regions_module.normalise(region)
        if key not in regions_module.REGIONS:
            return _respond({
                "error": f"No region called {region.strip()!r}. Call list_regions "
                         "for the available keys.",
                "anchorages": [],
            })
        bounds = regions_module.bounds_of(regions_module.REGIONS[key]["box"])
        south, west = bounds["south"], bounds["west"]
        north, east = bounds["north"], bounds["east"]
        area = {"region": key, "bounds": bounds}
    else:
        return _respond({"error": "Give either a region or a bbox.", "anchorages": []})

    days = max(0.0, min(float(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cells = _history.density(since, south, west, north, east, ANCHORAGE_CELL,
                             status="At anchor")
    found = anchorages_module.cluster(cells, ANCHORAGE_CELL)
    for anchorage in found:
        anchorage["area_nm2"] = anchorages_module.area_nm2(anchorage)

    return _respond({
        "data": {
            "source": "history",
            "days": days,
            "cell_degrees": ANCHORAGE_CELL,
            "minimum_vessels": anchorages_module.MIN_VESSELS,
            "note": (
                "Derived from vessels reporting At anchor, not from a chart. "
                "Counts are distinct vessels over the window, so a busy "
                "anchorage and a long-stay one are told apart. An anchorage "
                "outside receiver coverage does not appear at all."
            ),
        },
        "area": area,
        "anchorages": found,
    })


@mcp.resource("vessels://all")
def all_vessels() -> str:
    """The full vessel dataset as a JSON resource."""
    vessels, provenance = get_vessels()
    return _respond({"data": provenance, "vessels": [_tidy(v) for v in vessels]})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
