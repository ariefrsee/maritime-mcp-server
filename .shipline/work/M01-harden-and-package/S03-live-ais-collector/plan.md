---
pipeline_state:
  story_id: S03
  milestone: M01
  title: Live AIS collector
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S03-live-ais-collector
  started_at: 2026-09-14
  last_updated: 2026-09-14
  guardrails_loaded: [G1, G2, G3, G4, G5, G6]
---

# S03: Live AIS collector

> **Split from the original S02 on 2026-09-14, before any code was written.**
> S02 builds the offline half, the mapping layer and the vessel store, and can be
> verified with no API key. This story is the live half and is **blocked on a
> prerequisite outside my control**: an aisstream.io API key that only the user
> can create. The full investigation lives in `../S02-vessel-data-pipeline/plan.md`
> section 2 and is not repeated here.

## 1. What this is

S02 leaves a vessel store that nothing fills. This story fills it from the real
world. After it, asking what is near Port Klang returns ships that are genuinely
there right now, and the snapshot becomes what you get only when the feed is
unreachable.

## 2. Maturity assessment

The pipeline this feeds already exists once S02 closes: the mapping is written,
the store merges and evicts, and the tools already read through a seam that
prefers live data. What is missing is the network.

**Maturity rating: 3/10 at time of writing, expected 6/10 once S02 closes.**
The rating is low because none of it exists, not because it is hard. The
websocket client itself is about forty lines, following the vendor's published
example.

**Prerequisite satisfied 2026-09-14.** The user supplied an `AISSTREAM_API_KEY`
during S02 planning. It was verified working: 99 unique vessels observed over
Malaysian waters in a 300 second capture, which also confirms AC-1's threshold of
50 is realistic rather than guessed.

## 3. Guardrails that apply

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G1 | Every dependency gets an upper bound at the next major version | `websockets` is introduced here and needs a real ceiling, not an open range |
| G2 | Never write a checkable fact into a plan without running the command that checks it | The connection URL, the `compression="deflate"` requirement, the three second subscription window and the bounding box format all came from the vendor's published example and type definitions, fetched during planning |
| G3 | Resolve package data through the import system, never by walking from `__file__` | Unchanged, and the fallback snapshot still depends on it |
| G4 | Verify packaging with a built artifact installed outside the repository | `websockets` becomes a runtime dependency, so only a clean wheel install proves it is declared |
| G5 | An acceptance criterion must be evaluable at the phase that checks it | Every criterion here needs a live feed. That is the nature of the story and is why it was split out rather than left mixed with verifiable work |
| G6 | Read the staged file list before every commit | An API key must never reach a commit. This is the story where that risk is real |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected
- [ ] PRE-2: Cut `feat/S03-live-ais-collector`
- [ ] PRE-3: **S02 is closed.** This story builds directly on its store and mapping
- [x] PRE-4: `AISSTREAM_API_KEY` supplied and verified working during S02
      planning. **The key is a live secret: read it from the environment only,
      never write it to a file in the repository, and confirm before every
      commit that it is absent from the staged set**

## 5. Implementation steps

### Step 1: The collector

**Files touched:** new `maritime_mcp_server/collector.py`.

**What changes:** An asyncio task connecting to `wss://stream.aisstream.io/v0/stream`
with `compression="deflate"`, which the vendor's example comments say is required
to serve full bandwidth. The subscription must be sent within three seconds or
the connection closes. Bounding box covering Malaysian waters, approximately
latitude 0.5 to 7.5 and longitude 98.5 to 105.5, spanning the Strait of Malacca
and both coasts of the peninsula. Messages with `Valid: false` are discarded
before they reach the store. Exponential backoff on disconnect, with a floor and
a hard stop after repeated failures rather than an infinite loop against a free
service.

**How to check it worked:** with a key set, the store count rises above zero
within a few minutes. Without a key, the collector declines to start and says so
exactly once.

### Step 2: Wire it into the server lifecycle

**Files touched:** `maritime_mcp_server/server.py`.

**What changes:** Use the `lifespan` parameter on `FastMCP`, confirmed present in
1.30.0 by inspecting `FastMCP.__init__`, to start the collector on server start
and cancel it cleanly on shutdown.

**How to check it worked:** the server answers a handshake with no key set, using
snapshot data, and with a key set eventually answers with `source: live`.

### Step 3: Dependencies, packaging and documentation

**Files touched:** `pyproject.toml`, `README.md`.

**What changes:** Declare `websockets` with an upper bound per G1. Document
`AISSTREAM_API_KEY`, where to get one, and that the server works without it.
Per G4, prove it from a wheel in a clean environment.

**How to check it worked:** the clean environment installs `websockets` from
wheel metadata alone and the server runs there.

## 6. Acceptance criteria

Every criterion here needs the API key.

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | With a key set, the store holds more than 50 vessels within five minutes, none of which are from the bundled 18 | [x] |
| AC-2 | `vessels_near_port("Port Klang")` returns vessels whose positions differ between two calls several minutes apart | [x] |
| AC-3 | Killing the network mid session causes the collector to back off and retry rather than crash, and the tools fall back to the snapshot | [x] |
| AC-4 | The API key never appears in any log line, tool output, committed file or error message | [x] |
| AC-5 | `pyproject.toml` declares `websockets` with an upper bound, and a wheel installed in a clean environment outside the repository pulls it | [x] |
| AC-6 | Messages carrying `Valid: false` are not ingested | [x] |
| AC-7 | The server still starts, answers and falls back correctly when the key is absent | [x] |

### Evidence

All of the below came from driving the real server over stdio as a client would,
not from calling functions directly.

- **AC-1.** 63 vessels after five minutes of collection, against a threshold of
  50. None are from the bundled 18: the snapshot holds names like Bunga Mas Lima
  and Seri Alam, while live returns SEA SERENITY, ORKIM RELIANCE and
  ZHONG CHUAN 701.
- **AC-2.** Two samples 180 seconds apart. 35 vessels present in both, of which
  **15 had changed position**, moving 0.35 to 0.71 nautical miles, which is
  consistent with 7 to 14 knots. 28 vessels were new in the second sample, and
  3 gained their type and size during the gap, for example SOUTHERN RESPECT
  resolving to a 244m tanker bound for SG PEBGC.
- **AC-3.** Tested against an unroutable endpoint rather than by abusing the
  live service. Four `ConnectionRefusedError` retries with growing backoff, then
  `Giving up on live AIS after 4 consecutive failures`, after which
  `search_vessels` returned `source: snapshot` with 18 vessels. The collector
  logs the exception **type**, never its message, because a websocket handshake
  error can echo the request URL and the key rides in the subscription frame.
- **AC-4.** Checked programmatically across every captured stderr line and the
  full JSON of both tool responses: `API key present in any stderr line: False`,
  `API key present in tool output: False`. A repository-wide grep for the key
  returns nothing.
- **AC-5.** Wheel metadata reads `Requires-Dist: websockets<18,>=17` and
  `Requires-Python: >=3.11`. Installed into a venv created outside the
  repository that had never held `websockets`, it pulled 17.1, and the collector
  imported and correctly declined to start without a key.
- **AC-6.** A `PositionReport` with `Valid: false` returned `False` from
  `handle()` and left the store at one vessel rather than two. `handle()` was
  also fed malformed JSON, an empty string, `{}`, `[]`, `null`, `None`, an
  integer and a `SubscriptionConfirmation`; all returned `False` and none raised.
- **AC-7.** With the variable unset the server logged exactly one line,
  `AISSTREAM_API_KEY is not set, so live AIS is off`, and answered from the
  snapshot with correct provenance.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `maritime_mcp_server/collector.py` | websocket client, subscription, filtering, reconnect |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/server.py` | lifespan wiring |
| `pyproject.toml` | `websockets` with a ceiling |
| `README.md` | the API key and what live mode does and does not guarantee |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| The MCP process is short lived, so the store starts empty every time the client launches the server | certain | the first questions after startup get snapshot data | Inherent to streaming AIS under MCP and not solvable here. It is why the fallback and the provenance field exist |
| Reconnect logic hammers a free service and the account is blocked | medium | the story ends and the account may not come back | Exponential backoff with a floor, and a hard stop after repeated failures |
| The API key leaks into a log, a commit or an error message | low | severe and public | AC-4 tests it explicitly, G6 applies at gate 3, and the key is read from the environment only |
| Coverage over Malaysian waters is thinner than expected, so few vessels arrive | medium | AC-1's threshold of 50 is not met and the story looks failed when the code is fine | If it happens, record the real number observed and judge the criterion against reality rather than quietly lowering it |
| The user's key has limits the free tier documentation does not state | medium | unexpected disconnects | The vendor documents three connections per account and one subscription update per second. Anything beyond that is unknown until observed |

## 9. Out of scope

- **The `mcp` 2.x migration.** S04.
- **Historical positions or tracks.** aisstream does not replay missed events, so
  history would mean a database.
- **Global coverage.** One bounding box over Malaysian waters.
- **A real test suite.** Milestone goal G2, still unstarted.
- **Input validation.** Milestone goal G3, still unstarted.

## 10. Verification

```
# snapshot mode must keep working, covers AC-7
env -u AISSTREAM_API_KEY .venv/bin/python -m maritime_mcp_server.smoke_test

# live mode, covers AC-1 and AC-2, requires the key
AISSTREAM_API_KEY=... python tools/compare_wire.py --out live.json

# secret hygiene, covers AC-4
grep -rn "$AISSTREAM_API_KEY" . --exclude-dir=.git   # expect no matches

# packaging, per G4
python -m build --wheel && pip install dist/*.whl    # in a clean env outside the repo
```

**Result:** run on 2026-09-14. All seven criteria met, verified against the real
service over the real protocol.

## 11. Divergence log

### D-1: the websocket client forces a Python floor change

**When:** preflight, before any code.

**What happened:** `websockets` 17.1, the current release, declares
`Requires-Python: >=3.11`. This project declared `>=3.10`. Separately,
`asyncio.timeout`, which the read loop wants, also arrived in 3.11.

**Options considered:** raise the floor to 3.11 and take `websockets` 17;
stay at 3.10 with `websockets>=16.1,<17` and use `asyncio.wait_for`; or widen to
`>=16.1,<18` and support both, which means two resolution paths and no test
suite to cover either.

**Raised at a gate rather than decided in the build, per G9,** since narrowing
`requires-python` changes what the package promises. The user chose to raise the
floor. Python 3.10 reaches end of security support in October 2026, about a
month from this story.

**Effect:** `requires-python = ">=3.11"`, `websockets>=17,<18`.

### D-2: a clean websocket close counts as a failure for backoff

**When:** step 1, writing the retry loop.

**What happened:** the obvious loop treats a returning `_session()` as success
and reconnects immediately. A server that accepts a connection and closes it at
once, which is what a rejected key looks like, then becomes a hot loop against a
free service.

**Fix:** a clean return increments the failure counter exactly as an exception
does. Only inbound messages represent success. Combined with
`MAX_CONSECUTIVE_FAILURES`, a persistently unhappy endpoint is abandoned rather
than hammered.

### D-3: a vessel can report its type and still have no length

**When:** verification, reading the AC-2 output.

**What happened:** MARQUIS DE PRIE gained `type: Cargo` and a destination in the
gap between samples, but `length_m` stayed null, which initially read as a merge
bug.

**Why it is correct:** `ShipStaticData` carries both `Type` and `Dimension`, but
that vessel transmitted zero hull dimensions. `length_from_dimension` returns
`None` for a zero total rather than reporting a 0 metre ship. Guardrail G8 in
action: an absent value stays absent instead of becoming a plausible number.

**No change made.** Recorded because it looks like a defect and is not.

### D-4: the retry policy passed every test and was still wrong

**When:** while writing the retro, after all seven criteria had been met.

**What happened:** `failures` counted upward for the life of the process and was
never reset. A session that connected and delivered thousands of messages left
the counter exactly where it was. After eight failures accumulated across hours
of otherwise healthy operation, the collector would give up permanently and the
server would serve the snapshot with no further logging.

**Why no test caught it:** TC4 exercised total failure, an endpoint that never
connects. TC2, TC3 and TC8 exercised total success, a connection that never
drops. Real operation is neither. Nothing in the story tested a session that
works, then fails, then works again, which is the only shape in which the bug
appears.

**Fix:** `_session()` now reports whether it actually delivered any messages. A
productive session resets both the counter and the backoff delay. A clean close
that delivered nothing still counts as a failure, preserving the D-2 protection
against hot looping.

**Re-verified after the change**, because the change altered retry semantics:

```
unroutable endpoint : 4 retries, gives up, falls back to snapshot
mixed case          : 3 fails, 1 productive session, 4 more fails = 8 attempts
                      without the reset it would have stopped at 4
live path           : reconnected, 28 vessels near Tanjung Pelepas, ALS CERES
                      moored at 16.1nm with its correct 255m length
```
