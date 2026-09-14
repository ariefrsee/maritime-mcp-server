"""Shared fixtures.

Nothing here touches the network, needs an API key, or reads the wall clock.
Every time sensitive test injects its own `now`.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from maritime_mcp_server.store import VesselStore

FIXTURE = Path(__file__).parent / "data" / "ais_capture.json"


@pytest.fixture(scope="session")
def raw_messages() -> list[dict]:
    """199 real AIS messages captured over Malaysian waters on 2026-09-14."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def filled_store(raw_messages) -> VesselStore:
    """A store holding the whole fixture, with expiry pushed far enough out."""
    store = VesselStore(max_age=timedelta(days=3650))
    for message in raw_messages:
        store.ingest(message)
    return store


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio only. Trio is not a dependency here."""
    return "asyncio"
