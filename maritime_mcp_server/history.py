"""Durable vessel history, behind the in-memory store.

The store keeps the present: one entry per MMSI, expired after 30 minutes. This
keeps the past: every position ever ingested, so a later question like "when did
this vessel anchor" has something to read. You cannot compute an event from a
single snapshot.

Reads of "now" never come through here. `VesselStore.records()` answers from its
dict, so adding history costs the hot path nothing. This module is written on
ingest, read on startup to rehydrate, and read again by history queries.

sqlite3 is in the standard library, so this adds no dependency (G1).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH_VAR = "MARITIME_MCP_DB"
HISTORY_DAYS_VAR = "MARITIME_MCP_HISTORY_DAYS"

# How far back positions are kept. A guess at how far back a port call dispute
# reaches, and one constant to change when someone who files them says
# otherwise. Distinct from the store's 30-minute currency window: that decides
# whether a vessel is current, this decides whether its history is kept.
DEFAULT_HISTORY_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    mmsi        TEXT    NOT NULL,
    observed_at TEXT    NOT NULL,
    lat         REAL,
    lon         REAL,
    sog         REAL,
    cog         REAL,
    heading     REAL,
    status      TEXT
);
CREATE INDEX IF NOT EXISTS positions_mmsi_time ON positions (mmsi, observed_at);

CREATE TABLE IF NOT EXISTS vessels (
    mmsi        TEXT PRIMARY KEY,
    name        TEXT,
    type        TEXT,
    flag        TEXT,
    length_m    REAL,
    destination TEXT,
    updated_at  TEXT
);
"""


def default_db_path() -> str:
    """Where the database lives when nothing says otherwise.

    Never inside the package. An installed wheel is read-only, and a path
    derived from __file__ does not survive installation anyway (G3), so a
    database there fails on first write in the way hardest to diagnose.
    """
    override = os.environ.get(DB_PATH_VAR)
    if override:
        return override

    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    directory = root / "maritime-mcp-server"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / "vessels.db")


def history_days() -> int:
    raw = os.environ.get(HISTORY_DAYS_VAR)
    if not raw:
        return DEFAULT_HISTORY_DAYS
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_HISTORY_DAYS
    return days if days > 0 else DEFAULT_HISTORY_DAYS


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class VesselHistory:
    """Append-only position history for one database file.

    A connection per thread: the collector writes from its own task while tools
    read, and a sqlite3 connection is not safe to share across threads.
    """

    def __init__(self, path: str | None = None, retention_days: int | None = None):
        self.path = path or default_db_path()
        self.retention = timedelta(days=retention_days or history_days())
        self._local = threading.local()
        # A shared connection is kept for ":memory:", where each new connection
        # would otherwise be a different, empty database.
        self._shared = sqlite3.connect(self.path, check_same_thread=False) if self._in_memory else None
        self._shared_lock = threading.Lock()
        self._prepare(self._connect())

    @property
    def _in_memory(self) -> bool:
        return self.path == ":memory:"

    def _connect(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            self._local.conn = conn
        return conn

    # Columns added after the first release. A database written by an earlier
    # version opens fine and is migrated in place, rather than failing on the
    # first query against a column it has never heard of.
    ADDED_COLUMNS = (("positions", "cog", "REAL"), ("positions", "heading", "REAL"))

    # Values written by an earlier version that the current code can no longer
    # produce, and which are wrong rather than merely old. Kept as a list so the
    # reason for each is recorded next to it.
    #
    # "Unknown type 0": AIS ship type 0 means "not available", the type
    # equivalent of an unset navigational status. It was being labelled as an
    # unrecognised category and rehydrated back into the live view long after
    # the mapping was fixed. Other "Unknown type N" values are left alone: those
    # codes genuinely are unrecognised and reporting them as themselves is the
    # correct behaviour (G8).
    STALE_VALUES = (("vessels", "type", "Unknown type 0"),)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for table, column, kind in self.ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

        for table, column, value in self.STALE_VALUES:
            conn.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} = ?", (value,))
        # An UPDATE opens a transaction, and the journal mode cannot be changed
        # from inside one. ALTER TABLE above does not, which is why this only
        # started mattering when a data fix joined the schema fixes.
        conn.commit()

    def _prepare(self, conn: sqlite3.Connection) -> None:
        with self._guard():
            conn.executescript(SCHEMA)
            self._migrate(conn)
            if not self._in_memory:
                # Readers do not block the writer, which matters because a tool
                # call can land mid-ingest.
                conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()

    def _guard(self):
        """Serialise access when every thread shares one connection."""
        import contextlib

        return self._shared_lock if self._shared is not None else contextlib.nullcontext()

    # --- writing -------------------------------------------------------------

    def record_position(self, mmsi, observed_at, lat, lon, sog, status,
                        cog=None, heading=None) -> None:
        conn = self._connect()
        with self._guard():
            conn.execute(
                "INSERT INTO positions (mmsi, observed_at, lat, lon, sog, cog, heading, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(mmsi), _iso(observed_at), lat, lon, sog, cog, heading, status),
            )
            conn.commit()

    def record_identity(self, mmsi, observed_at, **fields) -> None:
        """Upsert what is known about a vessel, leaving unknown fields alone.

        AIS sends identity in pieces, so a later message carrying only a name
        must not blank a type learned earlier. COALESCE keeps the old value
        whenever the new one is null.
        """
        conn = self._connect()
        with self._guard():
            conn.execute(
                """
                INSERT INTO vessels (mmsi, name, type, flag, length_m, destination, updated_at)
                VALUES (:mmsi, :name, :type, :flag, :length_m, :destination, :updated_at)
                ON CONFLICT(mmsi) DO UPDATE SET
                    name        = COALESCE(excluded.name, vessels.name),
                    type        = COALESCE(excluded.type, vessels.type),
                    flag        = COALESCE(excluded.flag, vessels.flag),
                    length_m    = COALESCE(excluded.length_m, vessels.length_m),
                    destination = COALESCE(excluded.destination, vessels.destination),
                    updated_at  = excluded.updated_at
                """,
                {
                    "mmsi": str(mmsi),
                    "name": fields.get("name"),
                    "type": fields.get("type"),
                    "flag": fields.get("flag"),
                    "length_m": fields.get("length_m"),
                    "destination": fields.get("destination"),
                    "updated_at": _iso(observed_at),
                },
            )
            conn.commit()

    # --- reading -------------------------------------------------------------

    def track(self, mmsi, since: datetime, until: datetime | None = None) -> list[dict]:
        """One vessel's positions over a window, oldest first."""
        conn = self._connect()
        clause = "mmsi = ? AND observed_at >= ?"
        params: list = [str(mmsi), _iso(since)]
        if until is not None:
            clause += " AND observed_at <= ?"
            params.append(_iso(until))
        with self._guard():
            rows = conn.execute(
                f"SELECT observed_at, lat, lon, sog, cog, heading, status FROM positions"
                f" WHERE {clause} ORDER BY observed_at ASC",
                params,
            ).fetchall()
        return [
            {
                "observed_at": row[0],
                "lat": row[1],
                "lon": row[2],
                "speed_knots": row[3],
                "course_degrees": row[4],
                "heading_degrees": row[5],
                "status": row[6],
            }
            for row in rows
        ]

    def activity_by_hour(self, since: datetime, south, west, north, east) -> list[dict]:
        """Distinct vessels per hour in a box, split by what they reported.

        Counted in SQL rather than by pulling every row into Python: a fortnight
        of a busy strait is millions of positions, and the answer is a few
        hundred numbers.

        DISTINCT matters. A vessel moored alongside reports every three minutes,
        so counting rows would say twenty ships where there is one.
        """
        conn = self._connect()
        with self._guard():
            rows = conn.execute(
                """
                SELECT substr(observed_at, 1, 13) AS hour,
                       COUNT(*) AS positions,
                       COUNT(DISTINCT mmsi) AS vessels,
                       COUNT(DISTINCT CASE WHEN status = 'At anchor' THEN mmsi END) AS at_anchor,
                       COUNT(DISTINCT CASE WHEN status = 'Moored' THEN mmsi END) AS moored,
                       COUNT(DISTINCT CASE WHEN sog >= 3 THEN mmsi END) AS under_way
                FROM positions
                WHERE observed_at >= ?
                  AND lat BETWEEN ? AND ?
                  AND lon BETWEEN ? AND ?
                GROUP BY hour
                ORDER BY hour
                """,
                (_iso(since), south, north, west, east),
            ).fetchall()
        return [
            {"hour": r[0], "positions": r[1], "vessels": r[2],
             "at_anchor": r[3], "moored": r[4], "under_way": r[5]}
            for r in rows
        ]

    def density(self, since: datetime, south, west, north, east, cell: float,
                status: str | None = None) -> list[tuple]:
        """Recorded positions collapsed onto a grid, for a density map.

        Returns (lat, lon, vessels, positions) per occupied cell, counting
        distinct vessels as well as reports: one ship anchored for two days
        produces hundreds of positions in a single cell and would otherwise
        outweigh a hundred ships passing through it.

        Aggregated in SQL. Three hundred thousand positions is too much to send
        to a browser; nine thousand cells is not.

        `status` narrows it to one reported state, which is how the anchorage
        map is built: the same grid, counting only vessels that said they were
        at anchor.
        """
        conn = self._connect()
        with self._guard():
            rows = conn.execute(
                """
                SELECT ROUND(lat / ?) * ? AS la,
                       ROUND(lon / ?) * ? AS lo,
                       COUNT(DISTINCT mmsi) AS vessels,
                       COUNT(*) AS positions
                FROM positions
                WHERE observed_at >= ?
                  AND lat IS NOT NULL
                  AND lat BETWEEN ? AND ?
                  AND lon BETWEEN ? AND ?
                  AND (? IS NULL OR status = ?)
                GROUP BY la, lo
                """,
                (cell, cell, cell, cell, _iso(since), south, north, west, east,
                 status, status),
            ).fetchall()
        return [(round(r[0], 5), round(r[1], 5), r[2], r[3]) for r in rows]

    def tracks_since(self, since: datetime) -> dict:
        """Every vessel's positions since a cutoff, keyed by MMSI.

        One query rather than one per vessel: asking for five thousand tracks
        individually is five thousand round trips to answer a question about a
        single leg.
        """
        conn = self._connect()
        with self._guard():
            rows = conn.execute(
                "SELECT mmsi, observed_at, lat, lon FROM positions"
                " WHERE observed_at >= ? AND lat IS NOT NULL"
                " ORDER BY mmsi, observed_at",
                (_iso(since),),
            ).fetchall()
        tracks: dict[str, list] = {}
        for mmsi, observed_at, lat, lon in rows:
            tracks.setdefault(mmsi, []).append(
                {"observed_at": observed_at, "lat": lat, "lon": lon})
        return tracks

    def latest_positions(self, since: datetime) -> list[dict]:
        """The newest position per vessel since a cutoff, for rehydrating.

        Joined to identity so a restored vessel comes back with its name rather
        than as a bare MMSI.
        """
        conn = self._connect()
        with self._guard():
            rows = conn.execute(
                """
                SELECT p.mmsi, p.observed_at, p.lat, p.lon, p.sog, p.cog, p.heading,
                       p.status, v.name, v.type, v.flag, v.length_m, v.destination
                FROM positions p
                JOIN (
                    SELECT mmsi, MAX(observed_at) AS newest
                    FROM positions WHERE observed_at >= ? GROUP BY mmsi
                ) latest ON latest.mmsi = p.mmsi AND latest.newest = p.observed_at
                LEFT JOIN vessels v ON v.mmsi = p.mmsi
                """,
                (_iso(since),),
            ).fetchall()
        return [
            {
                "mmsi": r[0],
                "observed_at": r[1],
                "lat": r[2],
                "lon": r[3],
                "speed_knots": r[4],
                "course_degrees": r[5],
                "heading_degrees": r[6],
                "status": r[7],
                "name": r[8],
                "type": r[9],
                "flag": r[10],
                "length_m": r[11],
                "destination": r[12],
            }
            for r in rows
        ]

    def fleet_track(self, since: datetime, limit: int) -> tuple[dict, bool]:
        """Every vessel's positions since a cutoff, grouped by MMSI.

        One query rather than one per vessel: playback needs the whole picture,
        and asking several hundred times is not an answer. Identity is joined in
        so a caller does not have to go looking for names separately.

        Returns the grouping and whether the row cap was reached. A caller that
        silently receives less than it asked for would draw vessels vanishing.
        """
        conn = self._connect()
        with self._guard():
            rows = conn.execute(
                """
                SELECT p.mmsi, p.observed_at, p.lat, p.lon, p.sog, p.cog, p.heading,
                       p.status, v.name, v.type, v.flag
                FROM positions p
                LEFT JOIN vessels v ON v.mmsi = p.mmsi
                WHERE p.observed_at >= ?
                ORDER BY p.mmsi ASC, p.observed_at ASC
                LIMIT ?
                """,
                (_iso(since), limit + 1),
            ).fetchall()

        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]

        fleet: dict = {}
        for r in rows:
            entry = fleet.get(r[0])
            if entry is None:
                entry = {"mmsi": r[0], "name": r[8], "type": r[9], "flag": r[10],
                         "positions": []}
                fleet[r[0]] = entry
            entry["positions"].append({
                "observed_at": r[1],
                "lat": r[2],
                "lon": r[3],
                "speed_knots": r[4],
                "course_degrees": r[5],
                "heading_degrees": r[6],
                "status": r[7],
            })
        return fleet, truncated

    def prune(self, now: datetime | None = None) -> int:
        """Drop positions past the retention window. Returns how many went."""
        now = now or datetime.now(timezone.utc)
        cutoff = now - self.retention
        conn = self._connect()
        with self._guard():
            cursor = conn.execute("DELETE FROM positions WHERE observed_at < ?", (_iso(cutoff),))
            conn.commit()
        return cursor.rowcount or 0

    def count_positions(self) -> int:
        conn = self._connect()
        with self._guard():
            return conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
