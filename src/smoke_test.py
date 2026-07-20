"""Offline smoke test — verifies the tool logic without an MCP client.

The @mcp.tool() decorator leaves the underlying function callable, so we can
exercise the tools directly and confirm they return sensible data before wiring
the server into a real MCP client.

Run:
    python -m src.smoke_test
"""

from __future__ import annotations

import json

from .server import search_vessels, vessel_details, vessels_near_port


def main() -> None:
    tankers = json.loads(search_vessels(vessel_type="Tanker", status="At anchor"))
    assert any(v["name"] == "Seri Alam" for v in tankers), "expected Seri Alam at anchor"
    print(f"search_vessels(Tanker, At anchor) -> {len(tankers)} vessel(s): "
          f"{[v['name'] for v in tankers]}")

    near = json.loads(vessels_near_port("Port Klang", radius_nm=30))
    assert near and "distance_nm" in near[0], "expected annotated vessels near Port Klang"
    print(f"vessels_near_port(Port Klang, 30nm) -> {len(near)} vessel(s), "
          f"nearest {near[0]['name']} at {near[0]['distance_nm']}nm")

    one = json.loads(vessel_details("Kowloon Express"))
    assert one.get("mmsi") == "477055221", "expected Kowloon Express MMSI"
    print(f"vessel_details('Kowloon Express') -> MMSI {one['mmsi']}, flag {one['flag']}")

    missing = json.loads(vessel_details("999999999"))
    assert "error" in missing, "expected error for unknown vessel"
    print(f"vessel_details('999999999') -> {missing['error']}")

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
