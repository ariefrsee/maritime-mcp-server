"""Offline smoke test — verifies the tool logic without an MCP client.

The @mcp.tool() decorator leaves the underlying function callable, so we can
exercise the tools directly and confirm they return sensible data before wiring
the server into a real MCP client.

Run:
    python -m maritime_mcp_server.smoke_test
"""

from __future__ import annotations

import json

from .server import all_vessels, search_vessels, vessel_details, vessels_near_port


def main() -> None:
    tankers = json.loads(search_vessels(vessel_type="Tanker", status="At anchor"))
    assert tankers["data"]["source"] in ("live", "snapshot"), "expected a provenance block"
    assert any(v["name"] == "Seri Alam" for v in tankers["vessels"]), "expected Seri Alam at anchor"
    print(f"search_vessels(Tanker, At anchor) -> [{tankers['data']['source']}] "
          f"{tankers['matches']} vessel(s): {[v['name'] for v in tankers['vessels']]}")

    near = json.loads(vessels_near_port("Port Klang", radius_nm=30))
    assert near["vessels"] and "distance_nm" in near["vessels"][0], "expected annotated vessels"
    nearest = near["vessels"][0]
    print(f"vessels_near_port(Port Klang, 30nm) -> [{near['data']['source']}] "
          f"{near['matches']} vessel(s), nearest {nearest['name']} at {nearest['distance_nm']}nm")

    one = json.loads(vessel_details("Kowloon Express"))
    assert one["vessel"]["mmsi"] == "477055221", "expected Kowloon Express MMSI"
    print(f"vessel_details('Kowloon Express') -> MMSI {one['vessel']['mmsi']}, "
          f"flag {one['vessel']['flag']}")

    missing = json.loads(vessel_details("999999999"))
    assert "error" in missing, "expected error for unknown vessel"
    print(f"vessel_details('999999999') -> {missing['error']}")

    everything = json.loads(all_vessels())
    assert everything["data"]["source"] in ("live", "snapshot"), "resource needs provenance too"
    print(f"vessels://all -> [{everything['data']['source']}] "
          f"{len(everything['vessels'])} vessel(s)")

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
