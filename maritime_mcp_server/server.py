"""Maritime vessel data — Model Context Protocol (MCP) server.

Exposes the vessel dataset as MCP tools over stdio, so any MCP-compatible client
(Claude Desktop, an agent framework, an IDE) can query live vessel data through
a standard protocol instead of a bespoke integration. This is the same tool
surface used by the companion `maritime-vessel-agent` project, published here as
a reusable MCP server.

Run:
    python -m maritime_mcp_server.server    # stdio transport (for MCP clients)

Wire into Claude Desktop by adding this server to claude_desktop_config.json —
see the README.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib.resources import files

from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .collector import Collector
from .store import VesselStore

DATA_FILE = files(__package__).joinpath("data/vessels.json")

PORT_COORDS = {
    "port klang": (3.00, 101.36),
    "tanjung pelepas": (1.36, 103.54),
    "penang": (5.41, 100.34),
    "malacca": (2.19, 102.25),
    "langkawi": (6.32, 99.85),
}

@asynccontextmanager
async def _lifespan(_server):
    """Run the AIS collector for as long as the server is up.

    Without an API key the collector declines to start and the server answers
    from its bundled snapshot, which is a supported mode rather than a failure.
    """
    store = VesselStore()
    collector = Collector(store)
    started = collector.start()
    if started:
        set_store(store)
    try:
        yield {"store": store, "collector": collector}
    finally:
        await collector.stop()
        set_store(None)


mcp = FastMCP("maritime-vessel-data", lifespan=_lifespan)


SNAPSHOT_DATE = "2026-07-20"

# The live store is filled by the collector, which arrives in S03. Until then
# this stays None and every answer comes from the bundled snapshot.
_store = None


def set_store(store) -> None:
    """Register the live vessel store. Called by the server lifespan hook."""
    global _store
    _store = store


@lru_cache(maxsize=1)
def _load_snapshot() -> list[dict]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _filter_text(value) -> str:
    """Normalise a filter the way the port lookup already normalises a port name.

    A filter of only whitespace means the same as no filter. Before this, a
    stray space made a filter match nothing, which returned a confidently wrong
    answer rather than an error.
    """
    return value.strip().lower() if isinstance(value, str) else ""


def _nearest_port(lat, lon) -> str | None:
    """Closest port from the known list. AIS does not transmit this."""
    if lat is None or lon is None:
        return None
    best, best_dist = None, None
    for name, (plat, plon) in PORT_COORDS.items():
        dist = _haversine_nm(plat, plon, lat, lon)
        if best_dist is None or dist < best_dist:
            best, best_dist = name, dist
    return best.title() if best else None


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
                r["nearest_port"] = _nearest_port(r.get("lat"), r.get("lon"))
            ages = [r.get("position_age_seconds") for r in records
                    if r.get("position_age_seconds") is not None]
            return records, {
                "source": "live",
                "vessel_count": len(records),
                "oldest_position_age_seconds": max(ages) if ages else None,
            }
    return _load_snapshot(), {
        "source": "snapshot",
        "vessel_count": len(_load_snapshot()),
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
) -> str:
    """Search the vessel dataset by type, flag state, and/or navigational status.

    Any argument left blank is ignored, and surrounding whitespace is ignored.
    Returns JSON with a "data" block stating the source of the data and a
    "vessels" list. When data.source is "snapshot" the positions are from a
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
    return json.dumps({"data": provenance, "matches": len(results), "vessels": results}, indent=2)


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
) -> str:
    """List vessels within a radius (nautical miles) of a named port.

    Recognized ports: Port Klang, Tanjung Pelepas, Penang, Malacca, Langkawi.
    Returns JSON with a "data" block stating the source, and a "vessels" list
    annotated with distance_nm, nearest first. When data.source is "snapshot"
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
    return json.dumps({"data": provenance, "port": port, "radius_nm": radius_nm,
                       "matches": len(hits), "vessels": hits}, indent=2)


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
        return json.dumps({
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
        return json.dumps({"data": provenance,
                           "error": f"No vessel found matching '{query}'."})
    if len(matches) > 1:
        return json.dumps(
            {
                "data": provenance,
                "error": f"'{query}' matched {len(matches)} vessels; be more specific.",
                "candidates": [{"mmsi": m.get("mmsi"), "name": m.get("name")} for m in matches],
            }
        )
    return json.dumps({"data": provenance, "vessel": matches[0]}, indent=2)


@mcp.resource("vessels://all")
def all_vessels() -> str:
    """The full vessel dataset as a JSON resource."""
    vessels, provenance = get_vessels()
    return json.dumps({"data": provenance, "vessels": vessels}, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
