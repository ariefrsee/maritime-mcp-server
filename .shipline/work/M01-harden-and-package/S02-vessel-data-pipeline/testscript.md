# S02 Test Script: Vessel data pipeline, offline half

**Story:** S02 | **Branch:** `feat/S02-vessel-data-pipeline` | **Date:** 2026-09-14

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails. Do not tick a case you did not actually run.

**Run by the assistant on 2026-09-14, at the user's instruction**, following the
same arrangement as S01. Recorded here plainly rather than glossed: every result
below was produced and read by the same party that wrote the code, which is a
weaker check than an independent run.

Nothing here needs an API key or a network connection. That was the point of
splitting the story.

```bash
cd /Users/ariefrse/maritime-mcp-server
git checkout feat/S02-vessel-data-pipeline
```

---

## Prerequisites

- [x] On branch `feat/S02-vessel-data-pipeline`
- [x] `.venv` exists with the project installed
- [x] No network required

---

## Test cases

### TC1: The recorded verify command still passes

**Covers:** AC-9

**Steps:**
1. `.venv/bin/python -m maritime_mcp_server.smoke_test`

**Expected:** five lines, each tagged `[snapshot]`, ending `All smoke checks passed.`

**Result:** [x] Pass

**Notes:** Output as expected. The smoke test was rewritten this story: it had to
change because the tool output shape changed, and it now also covers the
`vessels://all` resource, which it never touched before.

---

### TC2: Every answer says where it came from

**Covers:** AC-1

**Purpose:** The whole point of the story. An answer from a fixed sample must be
impossible to mistake for a live one.

**Steps:**
1. ```bash
   .venv/bin/python -c "
   import json
   from maritime_mcp_server.server import search_vessels, vessels_near_port, vessel_details, all_vessels
   for name, out in [('search', search_vessels()), ('near', vessels_near_port('Port Klang')),
                     ('details', vessel_details('Seri Alam')), ('resource', all_vessels())]:
       print(name, json.loads(out)['data'])"
   ```

**Expected:** all four carry a `data` block with `source: snapshot`,
`vessel_count: 18`, `snapshot_date: 2026-07-20` and a note saying the positions
are not current.

**Result:** [x] Pass

**Notes:** All four, including the error path of `vessel_details`, carry
provenance.

---

### TC3: Real captured messages map to the right shape

**Covers:** AC-2, AC-5, AC-6

**Purpose:** The mapping was written against 199 messages genuinely captured from
Malaysian waters, not invented ones.

**Steps:**
1. `.venv/bin/python tools/replay_sample.py`

**Expected:** 199 messages, 198 ingested and 1 rejected, that one being the
subscription confirmation. `key set difference = none` and
`missing-key records = 0`. Field coverage shows `flag` at 89 of 89 and `type` at
roughly 11 of 89.

**Result:** [x] Pass

**Notes:** 89 vessels, 3 non ship stations excluded, 8 held without a position.
The low `type` coverage is correct and important: static data arrives about once
per ten position reports, so most vessels genuinely have no known type yet.

---

### TC4: Unknown fields are null, never invented

**Covers:** AC-5

**Purpose:** The load bearing criterion. Guessing a plausible value would be
worse than admitting ignorance.

**Steps:**
1. Read the two example records printed at the end of TC3's output.

**Expected:** the position only example, `LNG GLORY`, has `type`, `length_m` and
`destination` all `null`, while position, name, flag and status are populated.

**Result:** [x] Pass

**Notes:** `LNG GLORY`, MMSI 314309000, Barbados, At anchor, with type, length
and destination all null. Nothing defaulted to a plausible looking value.

---

### TC5: Lookup tables agree with data that predates this story

**Covers:** AC-3

**Purpose:** A status or type table written wrong produces confident nonsense.
Checking against the bundled snapshot means checking against data written before
any of this existed.

**Steps:**
1. ```bash
   .venv/bin/python -c "
   from maritime_mcp_server import ais_mapping as m
   print(m.navigational_status(0), '|', m.navigational_status(1))
   print(m.flag_from_mmsi('533012345'), '|', m.flag_from_mmsi('477055221'))
   print(m.ship_type(70), '|', m.length_from_dimension({'A':194,'B':61}))"
   ```

**Expected:** "Under way using engine", "At anchor", Malaysia, Hong Kong, Cargo,
255.

**Result:** [x] Pass

**Notes:** Malaysia and Hong Kong match the flags already on `533012345` and
`477055221` in the bundled snapshot. 255m matches ALS CERES, a real captured
cargo vessel.

---

### TC6: An unrecognised code is reported, not guessed

**Covers:** AC-3

**Purpose:** The capture was one afternoon. Codes exist that it did not contain.

**Steps:**
1. ```bash
   .venv/bin/python -c "
   from maritime_mcp_server import ais_mapping as m
   print(m.navigational_status(99), '|', m.ship_type(123), '|', m.navigational_status(None))"
   ```

**Expected:** `Unknown status 99`, `Unknown type 123`, `None`. Never a silent
default and never a nearest guess.

**Result:** [x] Pass

**Notes:** `None` for a missing status is correct and load bearing: Class B
transponders do not transmit one at all, and defaulting them to "Under way"
would be a fabrication.

---

### TC7: The store merges two message types and evicts stale entries

**Covers:** AC-4

**Steps:**
1. Insert a `PositionReport` for one MMSI, then a later `ShipStaticData` for the
   same MMSI, and count records.
2. Insert a position with a 2 minute max age, then read at +1 minute and +5.
3. Feed a `Valid: false` message, a `SubscriptionConfirmation` and a garbage dict.

**Expected:** one merged record carrying both halves, not two. Present at +1,
gone at +5. All three bad inputs rejected.

**Result:** [x] Pass

**Notes:** Merged record had position from the first message and type Cargo,
length 180 and destination from the second. Eviction and all three rejection
paths behaved.

---

### TC8: A lighthouse is not a vessel

**Covers:** AC-2

**Purpose:** Found during build, not planned for. The feed carries aids to
navigation and malformed identifiers alongside ships.

**Steps:**
1. ```bash
   .venv/bin/python -c "
   from maritime_mcp_server import ais_mapping as m
   for x in ['563028460','995331385','9135649','003669145']:
       print(x, '|', m.mmsi_kind(x), '|', m.flag_from_mmsi(x))"
   ```

**Expected:** `563028460` ship Singapore. `995331385` aid to navigation Malaysia,
country digits taken from the middle of the number. `9135649` malformed, no flag.
`003669145` coast station, United States.

**Result:** [x] Pass

**Notes:** Non ship stations are excluded from vessel records and counted
separately. Flag coverage went from 90 of 92 to 89 of 89 as a result.

---

### TC9: The seam switches sources and falls back

**Covers:** AC-1

**Purpose:** S03 depends entirely on this working.

**Steps:**
1. With no store registered, call a tool and read `data.source`.
2. Register a store filled from the captured fixture, call again.
3. Register a store whose entries have all expired, call again.

**Expected:** `snapshot` with 18, then `live` with 89, then back to `snapshot`
with 18.

**Result:** [x] Pass

**Notes:** In live mode `vessels_near_port("Tanjung Pelepas")` returned 67 real
vessels including MANILA MAERSK (Denmark, Moored) and SEA PROSPERITY (Singapore,
Under way using engine).

---

### TC10: A vessel with identity but no position is still findable

**Covers:** AC-2

**Purpose:** Found during verification. AIS often gives a ship's name before its
whereabouts.

**Steps:**
1. With the fixture store registered, `vessel_details("ALS CERES")`.

**Expected:** found, with type Cargo, flag Singapore, length 255, destination
MYTTP, and `lat`, `lon`, `status` and `position_age_seconds` all `null`.

**Result:** [x] Pass

**Notes:** Failed before the fix, which is what prompted it. The distance tools
still correctly exclude vessels without a position.

---

### TC11: Package data ships and works away from the project root

**Covers:** AC-7, AC-8

**Purpose:** S01 proved package data is the thing most likely to be left out of a
wheel. This story adds a new data file.

**Steps:**
1. `.venv/bin/python -m build --wheel`
2. `unzip -l dist/*.whl | grep mid_countries`
3. Install the wheel into a venv created outside the repository.
4. From `cwd=/`, import the mapping and call `flag_from_mmsi`.

**Expected:** `mid_countries.json` present in the wheel, resolving to
`site-packages` in the clean environment, and Malaysia returned from `/`.

**Result:** [x] Pass

**Notes:** Resolved to the clean venv's own `site-packages`.

---

### TC12: The API key is nowhere in the repository

**Covers:** secret hygiene, guardrail G6

**Purpose:** A live key was used during this story. It must not have reached
anything trackable.

**Steps:**
1. `grep -rn "<the key>" . --exclude-dir=.git --exclude-dir=.venv`
2. `grep -rn AISSTREAM . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.shipline`
3. Read the full staged file list before committing.

**Expected:** zero occurrences of the key. No `AISSTREAM` references in code,
since the collector is S03.

**Result:** [x] Pass

**Notes:** Key held only in the session scratchpad at mode 600, outside the
repository, and passed to capture scripts by environment variable only. The
captured fixture was checked for it specifically.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC2, TC9 | [x] |
| AC-2 | TC3, TC8, TC10 | [x] |
| AC-3 | TC5, TC6 | [x] |
| AC-4 | TC7 | [x] |
| AC-5 | TC3, TC4 | [x] |
| AC-6 | TC3 | [x] |
| AC-7 | TC11 | [x] |
| AC-8 | TC11 | [x] |
| AC-9 | TC1 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Failures and what came of them:**

No case failed on the final run. Two failed during build and were fixed before
this script was written, both recorded as divergences in the plan:

1. **`vessel_details("ALS CERES")` returned not found** against real data,
   because the store required a position. TC10 now covers it. Divergence D-4.
2. **The smoke test crashed** with `TypeError: string indices must be integers`
   once provenance changed the output shape. Intended, but it is a breaking
   change to the tool contract that S01 had explicitly pinned. Divergence D-3.

Worth stating plainly: writing the test script after fixing both means these
cases were authored knowing the answer. They guard against regression from here,
but they did not find those bugs. Running the code against real data did.
