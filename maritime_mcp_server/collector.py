"""Background collector that fills the vessel store from live AIS.

Connects to aisstream.io over a websocket, subscribes to a bounding box, and
feeds every message into a VesselStore. Runs for as long as the server does.

The API key is read from AISSTREAM_API_KEY and is never logged, never written to
disk, and never included in an error message. Without it the collector declines
to start and says so once, leaving the server to answer from its bundled
snapshot.

Two details come from the vendor's own example and documentation rather than
from guesswork:

    * compression="deflate" is required to be served full message bandwidth.
    * The subscription must be sent within three seconds of connecting or the
      connection is closed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress

import websockets

log = logging.getLogger(__name__)

ENDPOINT = "wss://stream.aisstream.io/v0/stream"
API_KEY_VAR = "AISSTREAM_API_KEY"

# Malaysian waters: the Strait of Malacca, both coasts of the peninsula, and
# Sabah and Sarawak. The eastern edge was 105.5, which stopped short of Borneo
# entirely, so Kuching, Bintulu, Miri, Labuan, Kota Kinabalu and Sandakan were
# never subscribed to and could not have been received.
#
# Subscribing to water is not the same as having coverage of it. Most Malaysian
# ports return nothing because no receiver in the aisstream network is near
# them. This box stops the server refusing to ask; it does not create receivers.
#
# Ordered [[[lat, lon], [lat, lon]]] as the vendor's example shows.
DEFAULT_BOX = [[[0.5, 98.5], [7.5, 119.5]]]

# Reconnect backoff. A free service does not deserve a tight retry loop, so this
# backs off hard and gives up rather than hammering forever.
BACKOFF_START = 2.0
BACKOFF_MAX = 120.0
BACKOFF_FACTOR = 2.0
MAX_CONSECUTIVE_FAILURES = 8

PRUNE_INTERVAL = 60.0


class Collector:
    """Owns the websocket connection and the task that drains it."""

    def __init__(self, store, api_key=None, bounding_boxes=None):
        self._store = store
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_VAR)
        self._boxes = bounding_boxes or DEFAULT_BOX
        self._task = None
        self._prune_task = None
        self.messages_seen = 0
        self.connected = False

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def start(self) -> bool:
        """Begin collecting. Returns False when there is no key to use."""
        if not self.enabled:
            log.info(
                "%s is not set, so live AIS is off and answers will come from the "
                "bundled snapshot.", API_KEY_VAR
            )
            return False
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ais-collector")
            self._prune_task = asyncio.create_task(self._prune_loop(), name="ais-prune")
        return True

    async def stop(self) -> None:
        for task in (self._task, self._prune_task):
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = self._prune_task = None
        self.connected = False

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(PRUNE_INTERVAL)
            dropped = self._store.prune()
            if dropped:
                log.debug("pruned %d stale vessels", dropped)

    async def _run(self) -> None:
        delay = BACKOFF_START
        failures = 0
        while True:
            try:
                # A session that delivered messages was genuinely healthy, so it
                # clears the failure count. A clean close that delivered nothing
                # still counts as a failure, otherwise a server that accepts and
                # immediately drops the connection becomes a hot loop.
                if await self._session():
                    failures = 0
                    delay = BACKOFF_START
                else:
                    failures += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                # Deliberately logs the exception type, not the message, because
                # a websocket handshake error can echo the request URL.
                log.warning("AIS connection failed (%s), retry %d in %.0fs",
                            type(exc).__name__, failures, delay)
            finally:
                self.connected = False

            if failures >= MAX_CONSECUTIVE_FAILURES:
                log.error(
                    "Giving up on live AIS after %d consecutive failures. The server "
                    "keeps working from the bundled snapshot.", failures
                )
                return
            await asyncio.sleep(delay)
            delay = min(delay * BACKOFF_FACTOR, BACKOFF_MAX)

    async def _session(self) -> bool:
        """One connection. Returns True if it actually delivered any messages."""
        delivered = 0
        async with websockets.connect(ENDPOINT, compression="deflate") as ws:
            await ws.send(json.dumps({"APIKey": self._key, "BoundingBoxes": self._boxes}))
            self.connected = True
            log.info("AIS stream connected")
            async for raw in ws:
                self.handle(raw)
                delivered += 1
        return delivered > 0

    def handle(self, raw) -> bool:
        """Parse one frame and hand it to the store. Never raises."""
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return False
        self.messages_seen += 1
        try:
            return self._store.ingest(message)
        except Exception:
            log.debug("could not ingest a message", exc_info=True)
            return False
