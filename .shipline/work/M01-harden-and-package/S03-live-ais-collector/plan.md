---
pipeline_state:
  story_id: S03
  milestone: M01
  title: Live AIS collector
  current_phase: plan      # plan | build | verify | test | retro | deliver | done
  phases_completed: []
  approved_by_user: false
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
| AC-1 | With a key set, the store holds more than 50 vessels within five minutes, none of which are from the bundled 18. **Measured during S02 planning: 99 unique vessels in 300 seconds, 93 named** | [ ] |
| AC-2 | `vessels_near_port("Port Klang")` returns vessels whose positions differ between two calls several minutes apart, proving the data is moving | [ ] |
| AC-3 | Killing the network mid session causes the collector to back off and retry rather than crash, and the tools fall back to the snapshot with `source: snapshot` | [ ] |
| AC-4 | The API key never appears in any log line, tool output, committed file or error message. Verified by grepping the repository and all captured output | [ ] |
| AC-5 | `pyproject.toml` declares `websockets` with an upper bound at the next major version, and a wheel installed in a clean environment outside the repository pulls it | [ ] |
| AC-6 | Messages carrying `Valid: false` are not ingested, verified by feeding one through the collector's handler | [ ] |
| AC-7 | The server still starts, answers and falls back correctly when the key is absent, so snapshot mode is not regressed | [ ] |

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

**Result:** not yet run.
