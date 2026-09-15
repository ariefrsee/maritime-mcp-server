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
    if started:
        set_store(store)
    try:
        yield {"store": store, "collector": collector}
    finally:
        await collector.stop()
        set_store(None)
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


@mcp.resource("vessels://all")
def all_vessels() -> str:
    """The full vessel dataset as a JSON resource."""
    vessels, provenance = get_vessels()
    return _respond({"data": provenance, "vessels": [_tidy(v) for v in vessels]})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
