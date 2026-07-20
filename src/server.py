"""Maritime vessel data — Model Context Protocol (MCP) server.

Exposes the vessel dataset as MCP tools over stdio, so any MCP-compatible client
(Claude Desktop, an agent framework, an IDE) can query live vessel data through
a standard protocol instead of a bespoke integration. This is the same tool
surface used by the companion `maritime-vessel-agent` project, published here as
a reusable MCP server.

Run:
    python -m src.server          # stdio transport (for MCP clients)

Wire into Claude Desktop by adding this server to claude_desktop_config.json —
see the README.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "vessels.json"

PORT_COORDS = {
    "port klang": (3.00, 101.36),
    "tanjung pelepas": (1.36, 103.54),
    "penang": (5.41, 100.34),
    "malacca": (2.19, 102.25),
    "langkawi": (6.32, 99.85),
}

mcp = FastMCP("maritime-vessel-data")


@lru_cache(maxsize=1)
def _load_vessels() -> list[dict]:
    with open(DATA_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    radius_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return radius_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@mcp.tool()
def search_vessels(vessel_type: str = "", flag: str = "", status: str = "") -> str:
    """Search the vessel dataset by type, flag state, and/or navigational status.

    Any argument left blank is ignored. Matching is case-insensitive and partial.
    vessel_type examples: Tanker, Container, Cargo, Ferry, Tug, Fishing.
    status examples: "Under way", "At anchor", "Engaged in fishing".
    Returns a JSON list of matching vessels (may be empty).
    """
    results = []
    for v in _load_vessels():
        if vessel_type and vessel_type.lower() not in v["type"].lower():
            continue
        if flag and flag.lower() not in v["flag"].lower():
            continue
        if status and status.lower() not in v["status"].lower():
            continue
        results.append(v)
    return json.dumps(results, indent=2)


@mcp.tool()
def vessels_near_port(port: str, radius_nm: float = 30.0) -> str:
    """List vessels within a radius (nautical miles) of a named port.

    Recognized ports: Port Klang, Tanjung Pelepas, Penang, Malacca, Langkawi.
    Returns a JSON list of vessels, each annotated with distance_nm, nearest first.
    """
    key = port.strip().lower()
    if key not in PORT_COORDS:
        return json.dumps(
            {"error": f"Unknown port '{port}'. Known ports: {', '.join(PORT_COORDS)}"}
        )
    plat, plon = PORT_COORDS[key]
    hits = []
    for v in _load_vessels():
        dist = _haversine_nm(plat, plon, v["lat"], v["lon"])
        if dist <= radius_nm:
            hits.append({**v, "distance_nm": round(dist, 1)})
    hits.sort(key=lambda x: x["distance_nm"])
    return json.dumps(hits, indent=2)


@mcp.tool()
def vessel_details(query: str) -> str:
    """Look up a single vessel by exact MMSI or by (partial) name.

    Returns the full JSON record, or an error object if no unique match is found.
    """
    q = query.strip().lower()
    matches = [v for v in _load_vessels() if q == v["mmsi"] or q in v["name"].lower()]
    if not matches:
        return json.dumps({"error": f"No vessel found matching '{query}'."})
    if len(matches) > 1:
        return json.dumps(
            {
                "error": f"'{query}' matched {len(matches)} vessels; be more specific.",
                "candidates": [{"mmsi": m["mmsi"], "name": m["name"]} for m in matches],
            }
        )
    return json.dumps(matches[0], indent=2)


@mcp.resource("vessels://all")
def all_vessels() -> str:
    """The full vessel dataset as a JSON resource."""
    return json.dumps(_load_vessels(), indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
