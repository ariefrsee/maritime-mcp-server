"""Drive real captured AIS messages through the mapping and the store.

No network, no API key. The fixture is 199 messages captured from aisstream.io
over Malaysian waters on 2026-09-14, including every message type observed.

    python tools/replay_sample.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maritime_mcp_server.store import VesselStore  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "data" / "ais_capture.json"
SNAPSHOT_KEYS = {
    "mmsi", "name", "type", "flag", "lat", "lon",
    "speed_knots", "length_m", "destination", "nearest_port", "status",
}


def main() -> int:
    messages = json.loads(FIXTURE.read_text(encoding="utf-8"))
    store = VesselStore(max_age=timedelta(days=3650))  # fixture is historical
    kinds = Counter(m.get("MessageType") for m in messages)
    stored = sum(1 for m in messages if store.ingest(m))

    print(f"fixture:  {len(messages)} messages")
    for k, v in kinds.most_common():
        print(f"          {k:32} {v}")
    print(f"ingested: {stored}, rejected: {len(messages) - stored}")

    records = store.records()
    tally = store.counts()
    print(f"held:     {tally['total']} stations")
    print(f"          {tally['vessels']} vessels, {tally['not_a_ship']} not a ship, "
          f"{tally['no_position']} no position, {tally['expired']} expired")

    # Shape check: every record must carry exactly the snapshot's keys.
    bad = [r for r in records if not SNAPSHOT_KEYS.issubset(r)]
    extra = SNAPSHOT_KEYS.symmetric_difference(set(records[0]) - {"position_age_seconds"})
    print(f"shape:    missing-key records = {len(bad)}, key set difference = {extra or 'none'}")

    filled = Counter()
    for r in records:
        for k in SNAPSHOT_KEYS:
            if r.get(k) is not None:
                filled[k] += 1
    print("\nfield coverage across all vessels:")
    for k in sorted(SNAPSHOT_KEYS):
        print(f"          {k:14} {filled[k]:3}/{len(records)}")

    with_static = [r for r in records if r["type"]]
    print("\nexample with static data:" if with_static else "\nno vessel had static data")
    if with_static:
        print(json.dumps(with_static[0], indent=2))
    print("\nexample position only, unknowns must be null:")
    only_pos = [r for r in records if not r["type"]]
    print(json.dumps(only_pos[0], indent=2) if only_pos else "  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
