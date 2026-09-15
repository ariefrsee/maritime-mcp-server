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
from .history import VesselHistory

DEFAULT_MAX_AGE = timedelta(minutes=30)


def _parse_iso(value):
    """Read a timestamp written by the history layer."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class VesselStore:
    """Latest state per MMSI, merged across message types and aged out.

    Safe to write from the collector task while tools read from it, which is why
    every access takes the lock.
    """

    def __init__(self, max_age: timedelta = DEFAULT_MAX_AGE, history: VesselHistory | None = None):
        self._max_age = max_age
        self._vessels: dict[str, dict] = {}
        self._lock = threading.Lock()
        # History is optional so every existing test, and anyone using this as a
        # live-only view, keeps working with no database at all.
        self._history = history
        if history is not None:
            self._rehydrate()

    def _rehydrate(self) -> None:
        """Refill the cache from stored positions so a restart costs nothing.

        AIS has no backfill, so a cold process would otherwise wait out the full
        warm-up again. Only positions still inside the currency window are
        restored: anything older would have been pruned a moment later anyway.
        """
        cutoff = datetime.now(timezone.utc) - self._max_age
        for row in self._history.latest_positions(cutoff):
            observed = _parse_iso(row["observed_at"])
            if observed is None:
                continue
            body = {
                "Latitude": row["lat"],
                "Longitude": row["lon"],
                "Sog": row["speed_knots"],
            }
            # Restored fields are already mapped, so they are carried beside
            # the entry and overlaid in records() rather than being forced back
            # into a fake AIS body that to_record would have to re-decode.
            self._vessels[str(row["mmsi"])] = {
                "position": body,
                "static": None,
                "name": row["name"],
                "observed_at": observed,
                "restored": {
                    "status": row["status"],
                    "type": row["type"],
                    "flag": row["flag"],
                    "length_m": row["length_m"],
                    "destination": row["destination"],
                },
            }

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

        # Written outside the lock: the dict is the hot path and must not wait
        # on disk. The history is append-only, so ordering between writers does
        # not matter.
        if self._history is not None:
            self._write_history(kind, body, ident, observed)
        return True

    def _write_history(self, kind, body, ident, observed) -> None:
        mmsi = ident["mmsi"]
        if kind in ais_mapping.POSITION_TYPES:
            fields = ais_mapping.position_fields(body)
            self._history.record_position(
                mmsi,
                observed,
                fields["lat"],
                fields["lon"],
                fields["speed_knots"],
                fields["status"],
            )
        if ident["name"]:
            self._history.record_identity(mmsi, observed, name=ident["name"])
        if kind == "ShipStaticData":
            static = ais_mapping.static_fields(body)
            self._history.record_identity(
                mmsi,
                observed,
                type=static.get("type"),
                length_m=static.get("length_m"),
                destination=static.get("destination"),
                flag=ais_mapping.flag_from_mmsi(mmsi),
            )

    def _expired(self, entry, now) -> bool:
        return now - entry["observed_at"] > self._max_age

    def prune(self, now=None) -> int:
        """Drop entries older than max_age. Returns how many went.

        Also prunes stored history past its own, much longer, retention window.
        The two are different questions: max_age decides whether a vessel is
        current, retention decides whether its past is kept.
        """
        now = now or datetime.now(timezone.utc)
        with self._lock:
            stale = [k for k, v in self._vessels.items() if self._expired(v, now)]
            for k in stale:
                del self._vessels[k]
        if self._history is not None:
            self._history.prune(now)
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
                # A restored vessel knows things its rebuilt AIS body cannot
                # carry. Fill only the gaps: anything a live message has since
                # supplied wins over what was read off disk.
                restored = entry.get("restored")
                if restored:
                    for key, value in restored.items():
                        if value is not None and record.get(key) is None:
                            record[key] = value

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
