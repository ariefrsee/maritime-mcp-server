"""The collector: retry policy, message handling, and secret hygiene.

No sockets, no sleeping on real delays, no API key. `_session` is replaced with a
stub whose outcome sequence each test controls, so the retry loop is driven to
completion deterministically.
"""

from __future__ import annotations

import json
import logging

import pytest

from maritime_mcp_server import collector as collector_module
from maritime_mcp_server.collector import Collector
from maritime_mcp_server.store import VesselStore
from helpers import position

KEY = "test-key-not-a-real-one"


@pytest.fixture
def fast_backoff(monkeypatch):
    """Shrink the delays. The retry arithmetic is unchanged."""
    monkeypatch.setattr(collector_module, "BACKOFF_START", 0.001)
    monkeypatch.setattr(collector_module, "BACKOFF_MAX", 0.002)
    monkeypatch.setattr(collector_module, "MAX_CONSECUTIVE_FAILURES", 4)


def scripted(outcomes):
    """Return a _session stub that plays the given outcomes, then repeats the last.

    An outcome is True (delivered messages), False (clean close, delivered
    nothing), or an exception instance to raise.
    """
    calls = {"n": 0}

    async def _session(self):
        i = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        outcome = outcomes[i]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return _session, calls


# --- starting ----------------------------------------------------------------

def test_without_a_key_it_declines_to_start():
    c = Collector(VesselStore(), api_key=None)
    assert c.enabled is False
    assert c.start() is False
    assert c._task is None


def test_with_a_key_it_reports_enabled():
    assert Collector(VesselStore(), api_key=KEY).enabled is True


# --- retry policy ------------------------------------------------------------

@pytest.mark.anyio
async def test_a_clean_close_that_delivered_nothing_counts_as_a_failure(
        fast_backoff, monkeypatch):
    """G14. A server that accepts and immediately drops the connection is what a
    rejected key looks like. Treating that as success is an instant hot loop."""
    stub, calls = scripted([False])
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    c.start()
    await c._task
    assert calls["n"] == 4, "should give up after MAX_CONSECUTIVE_FAILURES"


@pytest.mark.anyio
async def test_exceptions_count_as_failures_too(fast_backoff, monkeypatch):
    stub, calls = scripted([ConnectionRefusedError("refused")])
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    c.start()
    await c._task
    assert calls["n"] == 4


@pytest.mark.anyio
async def test_a_productive_session_resets_the_failure_count(fast_backoff, monkeypatch):
    """AC-4, and guardrail G16.

    This is the case the real bug lived in. Three failures, one healthy session,
    then failures again. With the reset the collector attempts 3 + 1 + 4 = 8
    sessions. Without it, the counter never clears and it stops at 4.

    Removing the `failures = 0` line in collector.py makes this test fail.
    """
    stub, calls = scripted([False, False, False, True, False])
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    c.start()
    await c._task
    assert calls["n"] == 8, (
        "a healthy session must clear the failure count; got "
        f"{calls['n']} attempts, which is what a missing reset looks like"
    )


@pytest.mark.anyio
async def test_alternating_success_and_failure_never_gives_up(fast_backoff, monkeypatch):
    """The other half of G16: a flaky but working feed must keep running."""
    outcomes = [True, False] * 20
    stub, calls = scripted(outcomes)
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    c.start()
    import asyncio
    await asyncio.sleep(0.05)
    still_running = not c._task.done()
    await c.stop()
    assert still_running, "alternating outcomes should never reach the failure cap"
    assert calls["n"] > 4, "and it should have kept trying well past the cap"


@pytest.mark.anyio
async def test_stop_cancels_cleanly(fast_backoff, monkeypatch):
    stub, _ = scripted([True])
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    c.start()
    await c.stop()
    assert c._task is None
    assert c.connected is False


# --- message handling --------------------------------------------------------

def test_a_valid_frame_reaches_the_store():
    store = VesselStore()
    c = Collector(store, api_key=KEY)
    assert c.handle(json.dumps(position(533012345))) is True
    assert len(store) == 1


def test_an_invalid_frame_is_rejected():
    store = VesselStore()
    c = Collector(store, api_key=KEY)
    bad = position(533012345)
    bad["Message"]["PositionReport"]["Valid"] = False
    assert c.handle(json.dumps(bad)) is False
    assert len(store) == 0


@pytest.mark.parametrize("junk", ["not json", "", "null", "[]", "{}", None, 12345,
                                  '{"MessageType":"SubscriptionConfirmation","Message":{}}'])
def test_handle_never_raises(junk):
    c = Collector(VesselStore(), api_key=KEY)
    assert c.handle(junk) is False


def test_messages_seen_counts_parsed_frames_including_rejected_ones():
    c = Collector(VesselStore(), api_key=KEY)
    c.handle(json.dumps(position(533012345)))
    c.handle('{"MessageType":"SubscriptionConfirmation","Message":{}}')
    c.handle("not json")            # never parsed, so not counted
    assert c.messages_seen == 2


def test_a_store_that_raises_does_not_bring_down_the_collector():
    class Exploding:
        def ingest(self, _):
            raise RuntimeError("boom")
    c = Collector(Exploding(), api_key=KEY)
    assert c.handle(json.dumps(position(533012345))) is False


# --- secret hygiene ----------------------------------------------------------

@pytest.mark.anyio
async def test_the_api_key_never_reaches_a_log_record(fast_backoff, monkeypatch, caplog):
    """G13 and AC-7.

    The key travels in the subscription frame, and a websocket handshake failure
    can echo the request. The collector must log the exception type, never its
    message. Here the exception message deliberately contains the key.
    """
    boom = ConnectionError(f"handshake failed for wss://stream?apikey={KEY}")
    stub, _ = scripted([boom])
    monkeypatch.setattr(Collector, "_session", stub)
    c = Collector(VesselStore(), api_key=KEY)
    with caplog.at_level(logging.DEBUG, logger="maritime_mcp_server.collector"):
        c.start()
        await c._task
    everything = "\n".join(r.getMessage() for r in caplog.records)
    assert everything, "the failure should have been logged at all"
    assert KEY not in everything, f"the API key leaked into a log record:\n{everything}"
    assert "ConnectionError" in everything, "the exception type should be logged"


def test_the_key_is_not_exposed_as_a_public_attribute():
    c = Collector(VesselStore(), api_key=KEY)
    public = {n: getattr(c, n) for n in dir(c) if not n.startswith("_")
              and not callable(getattr(c, n))}
    assert KEY not in repr(public)


# --- how much water is subscribed to -----------------------------------------

OLD_BOX_EAST_EDGE = 105.5

EAST_MALAYSIAN_PORTS = {
    "Kuching": (1.57, 110.34), "Bintulu": (3.26, 113.06), "Miri": (4.40, 113.99),
    "Labuan": (5.28, 115.24), "Kota Kinabalu": (5.98, 116.07), "Sandakan": (5.84, 118.12),
}


def _inside(box, lat, lon):
    (south, west), (north, east) = box
    return south <= lat <= north and west <= lon <= east


def test_the_box_reaches_sabah_and_sarawak():
    """AC-1. Half of Malaysia is east of where this box used to stop."""
    box = collector_module.DEFAULT_BOX[0]
    for port, (lat, lon) in EAST_MALAYSIAN_PORTS.items():
        assert _inside(box, lat, lon), f"{port} is outside the subscribed box"


def test_the_previous_box_excluded_all_of_them():
    """AC-2. Pins the change to its reason, not to a number.

    Every East Malaysian port sat outside the old eastern edge, so none had ever
    been requested. An earlier probe in this project reported zero vessels at
    Bintulu while Bintulu was not being subscribed to, which measured nothing.
    """
    for port, (_, lon) in EAST_MALAYSIAN_PORTS.items():
        assert lon > OLD_BOX_EAST_EDGE, f"{port} would have been inside the old box"


def test_the_peninsula_is_still_covered():
    box = collector_module.DEFAULT_BOX[0]
    for lat, lon in ((3.00, 101.36), (1.36, 103.54), (5.41, 100.34), (2.52, 101.80)):
        assert _inside(box, lat, lon)


def test_there_is_still_exactly_one_bounding_box():
    """AC-7. The vendor closes the connection if the subscription is malformed."""
    assert len(collector_module.DEFAULT_BOX) == 1
    assert len(collector_module.DEFAULT_BOX[0]) == 2
