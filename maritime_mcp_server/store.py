"""In memory store of the latest known state for each vessel.

AIS delivers a vessel's position and its identity in separate messages, at very
different rates. In a 300 second capture over Malaysian waters there were 178
position reports against 19 static data messages, so for most vessels most of the
time the type, destination and length are simply not known yet. This store holds
both halves as they arrive and hands back whatever is known, with the unknown
parts left as None.

Entries expire. A vessel that stopped transmitting is not still there, and
reporting its last position as though it were current would be a lie.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from . import ais_mapping

DEFAULT_MAX_AGE = timedelta(minutes=30)


class VesselStore:
    """Latest state per MMSI, merged across message types and aged out.

    Safe to write from the collector task while tools read from it, which is why
    every access takes the lock.
    """

    def __init__(self, max_age: timedelta = DEFAULT_MAX_AGE):
        self._max_age = max_age
        self._vessels: dict[str, dict] = {}
        self._lock = threading.Lock()

    def ingest(self, message) -> bool:
        """Take one raw aisstream message. Returns True if it was stored.

        Messages that carry no position or identity, such as the subscription
        confirmation, and messages flagged invalid by the transmitter, are
        dropped rather than stored.
        """
        if not isinstance(message, dict):
            return False
        kind = message.get("MessageType")
        body = (message.get("Message") or {}).get(kind)
        if not isinstance(body, dict):
            return False
        if body.get("Valid") is False:
            return False

        ident = ais_mapping.identity(message)
        mmsi = ident["mmsi"]
        if not mmsi:
            return False

        observed = ident["observed_at"] or datetime.now(timezone.utc)

        with self._lock:
            entry = self._vessels.setdefault(
                mmsi, {"position": None, "static": None, "name": None, "observed_at": observed}
            )
            if ident["name"]:
                entry["name"] = ident["name"]
            if kind in ais_mapping.POSITION_TYPES:
                entry["position"] = body
                entry["observed_at"] = observed
            elif kind == "ShipStaticData":
                entry["static"] = body
                # Static data alone does not prove the vessel is still moving,
                # so it refreshes the clock only if nothing newer is held.
                if observed > entry["observed_at"]:
                    entry["observed_at"] = observed
            else:
                return False
        return True

    def _expired(self, entry, now) -> bool:
        return now - entry["observed_at"] > self._max_age

    def prune(self, now=None) -> int:
        """Drop entries older than max_age. Returns how many went."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            stale = [k for k, v in self._vessels.items() if self._expired(v, now)]
            for k in stale:
                del self._vessels[k]
        return len(stale)

    def records(self, now=None, require_position: bool = True) -> list[dict]:
        """Every live vessel, in the server's record shape.

        By default only vessels with a known position are returned, because a
        vessel without one has no place on a map and would break the distance
        tools. Pass require_position=False for lookups that do not need a
        position, such as finding a vessel by name: AIS often delivers a ship's
        identity before, or without, any position report.
        """
        now = now or datetime.now(timezone.utc)
        out = []
        with self._lock:
            for mmsi, entry in self._vessels.items():
                if self._expired(entry, now):
                    continue
                if require_position and not entry["position"]:
                    continue
                # The feed carries aids to navigation, base stations and
                # malformed identifiers alongside ships. These tools answer
                # questions about vessels, so a lighthouse is not an answer.
                if ais_mapping.mmsi_kind(mmsi) != "ship":
                    continue
                record = ais_mapping.to_record(
                    position=entry["position"],
                    static=entry["static"],
                    name=entry["name"],
                    mmsi=mmsi,
                )
                age = now - entry["observed_at"]
                record["position_age_seconds"] = (
                    int(age.total_seconds()) if entry["position"] else None
                )
                out.append(record)
        return out

    def counts(self, now=None) -> dict:
        """Breakdown of what is held, for diagnostics and for the replay tool."""
        now = now or datetime.now(timezone.utc)
        tally = {"total": 0, "expired": 0, "no_position": 0, "not_a_ship": 0, "vessels": 0}
        with self._lock:
            for mmsi, entry in self._vessels.items():
                tally["total"] += 1
                if self._expired(entry, now):
                    tally["expired"] += 1
                elif not entry["position"]:
                    tally["no_position"] += 1
                elif ais_mapping.mmsi_kind(mmsi) != "ship":
                    tally["not_a_ship"] += 1
                else:
                    tally["vessels"] += 1
        return tally

    def __len__(self) -> int:
        with self._lock:
            return len(self._vessels)
