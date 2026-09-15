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

from . import regions

log = logging.getLogger(__name__)

ENDPOINT = "wss://stream.aisstream.io/v0/stream"
API_KEY_VAR = "AISSTREAM_API_KEY"

# Which sea areas to subscribe to. Names, boxes and the throughput each one
# costs all live in regions.py, along with the measurements behind the budget.
#
# Subscribing to water is not the same as having coverage of it. Most Malaysian
# ports return nothing because no receiver in the aisstream network is near
# them. Selecting a region stops the server refusing to ask; it does not create
# receivers, and widening the selection will not conjure any either.
REGIONS_VAR = "MARITIME_MCP_REGIONS"
DEFAULT_REGIONS = ("malaysia",)

# The vendor closes the connection if subscription updates arrive faster than
# one a second, so a caller changing region rapidly is paced rather than
# allowed to hang up its own feed.
RESUBSCRIBE_MIN_INTERVAL = 1.5

# Reconnect backoff. A free service does not deserve a tight retry loop, so this
# backs off hard and gives up rather than hammering forever.
BACKOFF_START = 2.0
BACKOFF_MAX = 120.0
BACKOFF_FACTOR = 2.0
MAX_CONSECUTIVE_FAILURES = 8

PRUNE_INTERVAL = 60.0


class Collector:
    """Owns the websocket connection and the task that drains it."""

    def __init__(self, store, api_key=None, bounding_boxes=None, region_keys=None):
        self._store = store
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_VAR)
        # An explicit box list still wins, so existing callers and tests that
        # pass one keep working and are not quietly re-pointed at a region.
        self._explicit_boxes = bounding_boxes
        self._regions = self._initial_regions(region_keys)
        self._ws = None
        self._last_subscribed_at = 0.0
        self._task = None
        self._prune_task = None
        self.messages_seen = 0
        self.connected = False

    @staticmethod
    def _initial_regions(region_keys) -> list[str]:
        """Regions from the caller, else the environment, else the default.

        An environment value naming nothing this server knows falls back rather
        than starting with an empty subscription, because aisstream requires at
        least one box and an empty list would fail the handshake every time
        with an error that says nothing about the typo that caused it.
        """
        if region_keys is not None:
            chosen = regions.parse_keys(region_keys)
            if chosen:
                return chosen
        raw = os.environ.get(REGIONS_VAR)
        if raw:
            chosen = regions.parse_keys(raw)
            unknown = regions.unknown_keys(raw)
            if unknown:
                log.warning("%s named unknown regions %s, ignoring them",
                            REGIONS_VAR, ", ".join(unknown))
            if chosen:
                return chosen
            log.warning("%s named no region this server knows, using %s",
                        REGIONS_VAR, ", ".join(DEFAULT_REGIONS))
        return list(DEFAULT_REGIONS)

    @property
    def regions(self) -> list[str]:
        return list(self._regions)

    def _boxes(self) -> list:
        if self._explicit_boxes:
            return self._explicit_boxes
        return regions.boxes_for(self._regions)

    def _subscription(self) -> str:
        return json.dumps({"APIKey": self._key, "BoundingBoxes": self._boxes()})

    async def set_regions(self, keys) -> dict:
        """Point the live subscription at a different set of regions.

        Sent on the open socket rather than by reconnecting, so the feed is not
        interrupted. Over budget is allowed but reported: the caller asked, and
        the honest answer is that it will drop, not a refusal dressed up as a
        limit that does not exist.
        """
        chosen = regions.parse_keys(keys)
        unknown = regions.unknown_keys(keys)
        if not chosen:
            return {"ok": False, "error": "No region named here is one this server knows.",
                    "unknown": unknown, "regions": self.regions}

        self._regions = chosen
        resubscribed = False
        if self._ws is not None:
            since = asyncio.get_running_loop().time() - self._last_subscribed_at
            if since < RESUBSCRIBE_MIN_INTERVAL:
                await asyncio.sleep(RESUBSCRIBE_MIN_INTERVAL - since)
            try:
                await self._ws.send(self._subscription())
                self._last_subscribed_at = asyncio.get_running_loop().time()
                resubscribed = True
            except Exception as exc:
                # The reconnect loop will pick the new regions up on its next
                # session, so a send failure here delays the change rather than
                # losing it.
                log.warning("could not update the subscription in place (%s); "
                            "it will apply on the next reconnect", type(exc).__name__)

        rate = regions.rate_for(chosen)
        return {
            "ok": True,
            "regions": chosen,
            "unknown": unknown,
            "applied_immediately": resubscribed,
            "estimated_rate_per_s": rate,
            "budget_per_s": regions.STABLE_BUDGET_PER_S,
            # Through the helper, not an inline comparison: rate is None when
            # any selected region is unmeasured, and None <= float raises.
            "within_budget": regions.within_budget(chosen),
        }

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
        """One connection. Returns True if it actually delivered any messages.

        The library's default keepalive is left on. It was seen to close a
        session with a ping timeout, but only while draining a whole-world
        subscription at around 80 messages a second, which is far outside the
        budget this collector is meant to run inside. At budgeted rates it held
        for three minutes in every run, and it is the only thing that notices a
        connection that has gone silent without closing.
        """
        delivered = 0
        async with websockets.connect(ENDPOINT, compression="deflate") as ws:
            self._ws = ws
            try:
                await ws.send(self._subscription())
                self._last_subscribed_at = asyncio.get_running_loop().time()
                self.connected = True
                log.info("AIS stream connected, regions: %s", ", ".join(self._regions))
                async for raw in ws:
                    self.handle(raw)
                    delivered += 1
            finally:
                self._ws = None
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
