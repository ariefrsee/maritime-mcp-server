---
pipeline_state:
  story_id: S02
  milestone: M01
  title: Vessel data pipeline, offline half
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S02-vessel-data-pipeline
  started_at: 2026-09-14
  last_updated: 2026-09-14
  guardrails_loaded: [G1, G2, G3, G4, G5, G6]
---

# S02: Vessel data pipeline, offline half

> **Split on 2026-09-14, before any code was written, at the user's approval.**
> The original S02 covered the whole live data story. Section 11 argued for a
> split and it was taken. This story is everything verifiable without an API key:
> the source seam, the field mapping and the vessel store. The websocket collector
> and the live wiring became S03, which is blocked on a key only the user can
> create. The investigation in section 2 covers both and is kept here in full.

## 1. What this is

Nothing a user can see changes in this story, and that is deliberate. It builds
the machinery that S03 plugs the real world into: a seam behind the tools so the
data source can change without touching them, a translation layer from what AIS
actually transmits into the shape these tools already promise, and a store that
merges a vessel's position with its identity and forgets it when it goes quiet.

The one visible change is honesty. Every answer starts saying where its data came
from and how old it is, so that once live data arrives, a stale answer can never
be mistaken for a current one.

## 2. Maturity assessment

Low. This is the first story that adds a moving part rather than rearranging
existing ones. The server currently has no network code, no configuration, no
background work and no concept of time. This story adds all four.

The size deserves a blunt statement up front: **this is materially larger than
S01, and larger than it looks.** The websocket client is the easy part. The work
is in the gap between what AIS transmits and what these tools promise.

### Dependencies

| Dependency | Status | What it provides |
|------------|--------|------------------|
| none | this story adds no dependency and needs no account | the whole point of the split |

Deferred to S03, listed here because the investigation covered them: an
aisstream.io account and API key, which only the user can create; `websockets`,
which the vendor example uses with `compression="deflate"`; and the `lifespan`
parameter on `FastMCP`, verified present in 1.30.0 by inspecting `__init__`.

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Three tools and one resource | complete. Their signatures do not change in this story | `maritime_mcp_server/server.py` |
| `_load_vessels()` with `@lru_cache` | the single point every tool reads through. This is the seam the story cuts at | `server.py` lines 38 to 41 |
| Bundled 18 vessel snapshot | becomes the fallback rather than the only source | `maritime_mcp_server/data/vessels.json` |
| Port coordinates and haversine | unchanged, and now applied to live positions | `server.py` lines 27 to 51 |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| Websocket client with reconnect and backoff | medium | medium. Networks fail, and a tight reconnect loop against a free service is abusive |
| In memory vessel store merging two message types | medium | medium. Position and identity arrive separately and at different rates |
| Field mapping from AIS wire format to the existing record shape | **high, and this is the real work** | high. Three lookup tables and one derivation, each a chance to produce confidently wrong data |
| Configuration, an API key from the environment | low | medium. A secret that must never be logged or committed |
| Staleness and provenance in tool output | medium | high if skipped. A stale position presented as current is worse than no answer |

**Maturity rating: 2/10.** Nothing of this exists. The one favourable fact is
that every tool reads through a single function, so the change has one seam
rather than many.

### The mismatch that is the actual story

**Revised 2026-09-14 against real captured traffic.** The user supplied an API
key before build started, so this table is no longer derived from the vendor's
schema alone. 375 seconds of live Malaysian traffic were captured and analysed.
Three entries in the original table were wrong and are corrected below.

| Field the tools return | Where it actually comes from | Difficulty |
|------------------------|------------------------------|------------|
| `mmsi` string | `MetaData.MMSI`, an integer | trivial cast |
| `name` | **`MetaData.ShipName`, present on every message.** Originally planned as `ShipStaticData.Name` requiring a merge. Space padded, needs trimming | trivial, and far easier than planned |
| `lat`, `lon` | `Latitude`, `Longitude` in the message body | direct |
| `speed_knots` | `Sog`. Observed range 0 to 17.5 | direct |
| `status` "Under way" | `NavigationalStatus`, integer. **Observed values 0, 1, 3, 5, 8 and 15**, so the full 0 to 15 table is needed, not a subset | 16 entry table |
| `type` "Cargo" | `Type` in `ShipStaticData`, integer. **Observed 33, 52, 70, 71, 72, 74, 79, 80, 86, 89, 90, 99.** Decade coded: 7x cargo, 8x tanker, 5x special craft, 3x fishing and towing | decade table with specific overrides |
| `destination` | `ShipStaticData.Destination`. **Free text and genuinely messy in the wild:** `SINGAPORE`, `SGSIN`, `SG SIN`, `OMSLL>SGSIN`, `KEPPEL K 15`. Not normalisable honestly | pass through trimmed, never "cleaned" |
| `length_m` | not transmitted. `Dimension.A + Dimension.B`. Verified on a real vessel: ALS CERES, A=194 B=61, length 255m | derivation, absent until static data arrives |
| `flag` | not transmitted. First three MMSI digits. **Observed 563 Singapore, 636 Liberia, 477 Hong Kong, 533 Malaysia, 538 Marshall Islands, 311 Bahamas, 525 Indonesia, 256 Malta, 352 Panama** | MID table |
| `nearest_port` | not transmitted. Computed from the existing port list | reuse existing haversine |

### What the live capture changed

Four corrections, all found before a line of code was written:

1. **Names are free.** `MetaData` rides on every message carrying `MMSI`,
   `ShipName`, `latitude`, `longitude` and `time_utc`. The plan's premise that
   names require merging two message streams was wrong. Merging is still needed
   for type, destination and dimensions, but not for identity.
2. **There is a fourth message type.** `StandardClassBPositionReport`, from Class
   B transponders on smaller vessels, appeared in the first capture. **It carries
   no `NavigationalStatus` at all.** Building only for `PositionReport` would
   have silently dropped these vessels.
3. **The body's `Timestamp` is not a clock.** It reads 13 and 16 because in AIS
   it is the second of the minute. The usable time is `MetaData.time_utc`. The
   original store design would have produced meaningless ages and evicted
   everything immediately.
4. **Strings are space padded.** `"SEA LONGEVITY       "` and
   `"MYTTP               "` need trimming at the boundary.

### Volume, measured

| Measure | Observed |
|---------|----------|
| Capture window | 300 seconds |
| Unique vessels | 99 |
| Vessels with a name | 93 |
| PositionReport | 178 |
| ShipStaticData | 19 |
| `Valid: false` messages | 0 in 197 sampled, but the field exists and is still checked |

Static data is roughly one message per ten position reports, which confirms that
type, destination and length will be absent for most vessels most of the time.
That makes AC-5, unknown fields are null and never invented, the load bearing
criterion of this story rather than a detail.

## 3. Guardrails that apply

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G1 | Every dependency gets an upper bound at the next major version | This story adds no dependency at all, which is the cleanest way to satisfy it. `websockets` arrives in S03 and the ceiling is that story's problem |
| G2 | Never write a checkable fact into a plan without running the command that checks it | Everything in the mismatch table above came from the vendor's `type-definition.yaml`, fetched and parsed, not recalled. The `lifespan` parameter was confirmed by inspecting `FastMCP.__init__`. What could **not** be checked is anything requiring an API key, and that is stated in the risks rather than glossed |
| G3 | Resolve package data through the import system, never by walking from `__file__` | The fallback snapshot is still package data and must keep using `importlib.resources`. Any new data file, such as the MID table, follows the same rule |
| G4 | Verify packaging with a built artifact installed outside the repository | This story adds a new package data file, the MID table. S01 proved package data is the thing most likely to be left out of a wheel, so it must be checked from a clean install again |
| G5 | An acceptance criterion must be evaluable at the phase that checks it | This is why the story was split. Every criterion below is evaluable during build with no key and no network |
| G6 | Read the staged file list before every commit | A `.env` file or a key pasted into a config would be catastrophic here. The staged list must be read with that specifically in mind |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected
- [ ] PRE-2: Cut `feat/S02-live-ais`
- [ ] PRE-3: Carry forward from S01 retro section 6. The `mcp` 2.x migration is
      now S03 and deliberately not in this story. Thin test coverage and absent
      input validation remain open and are made worse by this story, which is
      noted in the risks
- [ ] PRE-4: None. This story was split specifically so that it has no
      prerequisite on the user and no dependency on the API key

## 5. Implementation steps

### Step 1: Put a source seam behind the tools

**Files touched:** `maritime_mcp_server/server.py`.

**What changes:** `_load_vessels()` becomes `get_vessels()`, returning both the
records and a provenance object saying where they came from and how old they are.
The three tools and the resource change only in that they carry the provenance
into their output. No behaviour change yet: the only source is still the bundled
snapshot.

**How to check it worked:** the smoke test passes, and tool output gains a
`source` field reading `snapshot`. The wire comparison harness from the S03 plan
shows no other difference.

### Step 2: Build the field mapping, offline

**Files touched:** new `maritime_mcp_server/ais_mapping.py`, new
`maritime_mcp_server/data/mid_countries.json`.

**What changes:** Pure functions, no network. `navigational_status(int) -> str`
covering all of 0 to 15, `ship_type(int) -> str` decade coded, `flag_from_mmsi(str) -> str`,
and `length_from_dimension(dict) -> int | None`. Plus one function that folds a
position message and an optional `ShipStaticData` into the existing record shape.

It must handle **both** `PositionReport` and `StandardClassBPositionReport`. The
Class B variant has no `NavigationalStatus`, so status is `null` for those
vessels rather than defaulted to "Under way", which would be a fabrication.
Identity comes from `MetaData`, not from the message body.

This is the largest step and is deliberately separated from the network so it can
be tested without one.

**How to check it worked:** feed it the **real captured messages**, not invented
ones, and get records with the same nine keys as the bundled snapshot. Status 0
maps to "Under way using engine" and 1 to "At anchor". MMSI beginning 533 maps to
Malaysia and 477 to Hong Kong, checkable against the bundled snapshot where
`533012345` is Malaysia and `477055221` is Hong Kong. Type 70 maps to a cargo
category, verified against ALS CERES which is a real captured cargo vessel.

### Step 3: Build the vessel store

**Files touched:** new `maritime_mcp_server/store.py`.

**What changes:** An in memory dict keyed by MMSI, holding the latest position,
the most recent static data, and a real timestamp parsed from `MetaData.time_utc`
for each. **Not the body's `Timestamp` field, which is a second of the minute and
not a clock.** Merging happens here. Age based eviction so a vessel that stopped
transmitting does not linger as though it were current.

**How to check it worked:** unit exercise with synthetic messages. Insert a
position, then static data for the same MMSI, and confirm one merged record.
Confirm eviction by inserting with an old timestamp.

### Step 4: Make provenance visible

**Files touched:** `maritime_mcp_server/server.py`, tool docstrings.

**What changes:** Every tool's output states the source and the age of the data.
For live data, the age of the individual position. For fallback, the fact that it
is a static snapshot with a fixed date. Tool docstrings say this too, because the
docstring is what the AI reads to decide how to describe the answer.

**How to check it worked:** an answer from the snapshot cannot be mistaken for a
live one by reading the JSON alone.

### Step 5: Documentation

**Files touched:** `README.md`.

**What changes:** Document that tool output now carries provenance, and what the
`source` field means. No dependency changes: this story adds no third party
package, which is worth stating because the original combined plan did. Per G4,
still build a wheel and install it into a clean environment outside the
repository, because the new data file for the MID table must ship with it.

**How to check it worked:** the clean environment serves the MID table and the
mapping functions work there.

## 6. Acceptance criteria

Criteria marked **[key]** cannot be evaluated without the user's API key.

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | Every tool answers exactly as it does today, and output carries `source: snapshot` with the snapshot's date | [x] |
| AC-2 | The mapping functions convert a recorded AIS message into a record with the same nine keys as the bundled snapshot, no key missing and no extra key | [x] |
| AC-3 | Status code 0 maps to "Under way using engine" and 1 to "At anchor". MMSI prefix 533 maps to Malaysia and 477 to Hong Kong | [x] |
| AC-4 | The store merges a `PositionReport` and a later `ShipStaticData` for the same MMSI into one record, and evicts an entry older than the configured age | [x] |
| AC-5 | A vessel with position but no static data yields a record whose unknown fields are `null`, never invented | [x] |
| AC-6 | `tools/replay_sample.py` drives a recorded message sequence through mapping and store with no network and no API key | [x] |
| AC-7 | The server, the mapping and the MID table all resolve through `importlib.resources`, and everything works from a directory that is not the project root | [x] |
| AC-8 | A wheel installed in a clean environment outside the repository contains the MID table and the mapping works there | [x] |
| AC-9 | The recorded verify command still passes | [x] |

### Evidence

- **AC-1.** `search_vessels`, `vessels_near_port`, `vessel_details` and
  `vessels://all` all return a `data` block. With no store registered every one
  reports `{"source": "snapshot", "vessel_count": 18, "snapshot_date": "2026-07-20"}`
  plus a note saying the positions are not current.
- **AC-2.** 199 real captured messages replayed. `key set difference = none`
  and `missing-key records = 0`.
- **AC-3.** `navigational_status(0)` returns "Under way using engine",
  `navigational_status(1)` returns "At anchor". `flag_from_mmsi('533012345')`
  returns Malaysia and `flag_from_mmsi('477055221')` returns Hong Kong, matching
  the bundled snapshot which predates this story. `ship_type(70)` returns Cargo,
  checked against ALS CERES, a real captured cargo vessel, whose
  `Dimension {A:194, B:61}` yields the correct 255m.
- **AC-4.** Tested explicitly, not inferred. A position then a later static
  message for the same MMSI produced **one** record carrying both halves.
  Eviction: present at +1 minute against a 2 minute age, gone at +5. Rejections
  confirmed for `Valid: false`, for `SubscriptionConfirmation` and for garbage.
- **AC-5.** From the real capture, `LNG GLORY` has position, name, flag and
  status, with `type`, `length_m` and `destination` all `null` because it had
  not sent static data. Nothing defaulted.
- **AC-6.** Runs with no network and no key. 198 of 199 ingested, the one
  rejection being the subscription confirmation.
- **AC-7 and AC-8.** A wheel installed into a venv built outside the repository
  resolved the MID table to its own `site-packages` and answered correctly from
  `cwd=/`.
- **AC-9.** `All smoke checks passed.`

None of these need an API key. That is the point of the split.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `maritime_mcp_server/ais_mapping.py` | pure conversion from AIS wire fields to the record shape |
| `maritime_mcp_server/data/mid_countries.json` | Maritime Identification Digits to country, for the flag field |
| `maritime_mcp_server/store.py` | in memory vessel store, merging and eviction |
| `tools/replay_sample.py` | replays recorded messages through mapping and store with no network |
| `tests/data/ais_capture.json` | **real** captured Malaysian traffic, 197 messages including all four observed message types, so the pipeline is exercised against reality rather than invented input |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/server.py` | source seam and provenance in output. No lifespan wiring, that is S03 |
| `README.md` | what the `source` field means |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ~~The mapping is built against the vendor's schema but never against a real message~~ | **retired before build** | | The user supplied an API key during planning. 375 seconds of real traffic were captured and the mapping is now built against it. This risk found four genuine errors in the plan and is the reason the capture happened first |
| The captured sample is 375 seconds of one afternoon and may not contain every status code, type code or edge case that exists | high | a code appears in production that the tables do not cover | Every lookup falls through to a readable unknown value carrying the raw code, for example "Unknown status 12". Never a silent default and never a guess |
| This story ships nothing a user can see, so it is hard to tell whether it is any good | certain | a retro with little to say, and a temptation to declare success on structure alone | The criteria are written against observable output rather than internal design. AC-5 in particular pins a real decision, that unknown fields are null and never invented |
| Ship type and status code tables are written wrong and produce confidently incorrect labels | medium | high. Wrong data that looks right is worse than an error | AC-3 pins specific codes against flags already present in the bundled snapshot, so the tables are checked against data that predates this story |
| A vessel has position but no static data, so name, type and length are unknown | high, this is normal | tools return records with null fields | Decide and document the shape now: unknown fields are `null` and never invented. A vessel known only by MMSI is still a true answer |
| `Valid: false` messages are ingested as though they were good | medium | bad positions enter the store | The field exists in the vendor schema. Filtering belongs to the collector in S03, but the store must not assume its input is clean |

## 9. Out of scope

- **The websocket collector and live wiring.** Now S03, blocked on the API key.
- **The `mcp` 2.x migration.** Now S04. Doing it alongside this would make any
  failure ambiguous between a mapping bug and an SDK difference.
- **Historical positions or tracks.** The store holds the latest state per vessel.
  aisstream explicitly does not replay missed events, so history would mean a
  database, which is a different story.
- **Any port outside the existing five.** The port list is unchanged.
- **A real test suite.** Milestone goal G2 remains unstarted, and this story
  makes it more urgent by adding the first code with real logic in it. The
  offline steps here are exercised by hand, not by tests.
- **Input validation.** Still goal G3, still untouched.
- **Global coverage.** One bounding box over Malaysian waters. A wider box means
  far more traffic and a bigger store, with no benefit to the current port list.

## 10. Verification

```
# recorded verify command, unchanged
.venv/bin/python -m maritime_mcp_server.smoke_test

# offline pipeline, no key, no network. Covers AC-2 AC-3 AC-4 AC-5 AC-6
python tools/replay_sample.py

# provenance, covers AC-1
python tools/compare_wire.py --out snapshot.json

# works away from the project root, covers AC-7
cd / && python -c "from maritime_mcp_server.ais_mapping import flag_from_mmsi; print(flag_from_mmsi('533012345'))"

# packaging, per G4 and AC-8, in a clean env outside the repo
python -m build --wheel && pip install dist/*.whl
```

**Result:** run on 2026-09-14. All nine criteria met. See the evidence above and
the divergence log in section 11.

## 11. Divergence log

### D-1: the plan's field mapping was wrong in four places

**When:** before build, immediately after the user supplied an API key.

**What happened:** the plan was written against the vendor's published schema.
With a key available, 375 seconds of real Malaysian traffic were captured first.
Four of the plan's premises did not survive contact:

1. **Names do not require merging.** `MetaData` rides on every message with
   `MMSI`, `ShipName`, `latitude`, `longitude` and `time_utc`. The plan had names
   coming only from `ShipStaticData`.
2. **A fourth message type exists.** `StandardClassBPositionReport`, carrying no
   `NavigationalStatus`. Building only for `PositionReport` would have silently
   dropped these vessels.
3. **The body's `Timestamp` is not a clock.** It is the second of the minute.
   The store would have computed nonsense ages and evicted everything at once.
   The usable time is `MetaData.time_utc`, in Go's format, not ISO 8601.
4. **Strings are space padded** and `Destination` is unnormalisable free text:
   `SGSIN`, `SG SIN`, `OMSLL>SGSIN`, `KEPPEL K 15`.

**Effect:** the plan's section 2 was rewritten against measured reality before
any code was written. The story got simpler, not harder.

### D-2: the feed carries objects that are not ships

**When:** step 3, while investigating why two vessels had no flag.

**What happened:** MMSI `995331385` had no flag because it is not a ship. It is
an Aid to Navigation, a buoy or beacon, in the `99MIDxxxx` format where the
country digits sit in the middle rather than at the front. `9135649` is a
malformed seven digit identifier. The mapping correctly refused to guess a flag
for either, but the store was still listing both as vessels.

**Fix:** added `mmsi_kind()`, classifying ship, aid to navigation, coast station,
craft associated with parent ship, search and rescue aircraft, emergency beacon
and malformed, and `_mid_digits()`, which takes the country digits from the right
position for each. The store now excludes non-ship stations from vessel records
and counts them separately.

```
995331385  kind=aid to navigation   flag=Malaysia
9135649    kind=malformed           flag=None
```

Flag coverage went from 90 of 92 to 89 of 89.

**Scope note:** this was not in the plan. It is mapping fidelity, which is the
story's subject, and the alternative was shipping a tool that reports lighthouses
as ships.

### D-3: tool output shape changed, which breaks the previous contract

**When:** step 4.

**What happened:** adding provenance meant every tool now returns an envelope,
`{"data": {...}, "vessels": [...]}`, where it previously returned a bare list.
The smoke test failed with `TypeError: string indices must be integers`.

**Why it is intended:** AC-1 requires provenance to be visible, and an envelope
is the only place to put it. But it is a breaking change to the tool contract,
and S01's AC-8 had specifically pinned byte identical output. That guarantee is
deliberately broken here.

**Fix:** the smoke test was updated to the new shape and extended to cover the
`vessels://all` resource, which it had never touched.

### D-4: a details lookup should not require a position

**When:** verification, testing the seam against the real capture.

**What happened:** `vessel_details("ALS CERES")` returned not found, despite
ALS CERES being in the captured data. The store only returned vessels with a
known position, and that vessel had sent static data but no position report.

**Why the original was wrong:** requiring a position is right for the distance
tools, which cannot place a vessel without one, and wrong for a lookup by name.
AIS frequently delivers identity before whereabouts.

**Fix:** `records(require_position=False)` and `vessel_details` uses it.
`position_age_seconds` is `None` rather than a fabricated age when there is no
position.

```
ALS CERES -> Cargo, Singapore, 255m, destination MYTTP, lat null, lon null
```

### D-5: nearest_port was specified and never implemented

**When:** after the story was marked done, during a live end to end preview the
user asked for.

**What happened:** a real vessel came back with `"nearest_port": null`. Section 2
of this plan lists nearest port as "not transmitted, computed from the existing
port list, reuse existing haversine". No implementation step covered it, and no
acceptance criterion tested its value.

**Why it slipped:** AC-2 checks that a record has the same nine keys as the
snapshot. `nearest_port` was present as a key with a null value, so the criterion
passed while the field was never populated. The criterion tested shape, and the
plan promised behaviour.

**Fix:** `_nearest_port()` in `server.py`, applied to live records as they leave
`get_vessels()`. It lives in the server rather than the mapping layer, because
the port list is this project's knowledge and not something AIS provides.

```
nearest_port populated: 89/89 live vessels
distribution: {'Tanjung Pelepas': 67, 'Malacca': 20, 'Port Klang': 2}
```

Vessels without a position correctly keep `null`.

**Why this matters beyond the fix:** this is the second time in this story that a
criterion passed while the intent behind it failed. G5 says a criterion must be
evaluable at the phase that checks it. It does not say a criterion must actually
test the thing it is standing in for. That gap is real and is recorded as G11.
