---
pipeline_state:
  story_id: S26
  milestone: M04
  title: Port Dickson board
  current_phase: verify    # plan | build | verify | test | retro | deliver | done
  phases_completed: [build]
  approved_by_user: true   # 2026-10-15, in conversation: "ok write it all then start"
  branch: feat/S26-port-dickson-board
  started_at: 2026-10-15
  last_updated: 2026-10-16
  guardrails_loaded: [G2, G7, G8, G9, G10, G11, G15, G17, G18, G19, G23, G24, G26, G27, G28, G29, G6]
---

# S26: Port Dickson board

## 1. What this is

A port agent at Port Dickson can ask one question and get the morning's
picture: which ships are at Port Dickson now and since when, which ships have
declared it as their destination and how far off they are, and which ships left
in the last two days. Tugs, ferries and the other craft that live in the port
are kept in a separate list so they do not bury the real port calls. Times are
given as windows ("arrived between 13:00 and 14:00") because a ship stopped at
Port Dickson is only heard about once an hour.

Design and the measurements behind it:
`oceantrack-dashboard/docs/superpowers/specs/2026-10-15-port-dickson-board-design.md`
(committed on `feat/port-dickson-board` as 94bdcc9). This story is the server
half. The dashboard page is separate work in the other repository.

## 2. Maturity assessment

### Dependencies

| Dependency | Status | What it provides |
|------------|--------|------------------|
| History database | Live, 2,811,551 positions since 2026-09-15 (checked 2026-10-15) | Every fix and the latest identity per vessel |
| `vessels` table identity columns | Present: name, type, flag, length_m, destination, eta_declared and more (PRAGMA checked) | Names, types, declared destination and ETA |
| `PORT_COORDS["port dickson"]` | Present in server.py, (2.52, 101.80) | The port centre |
| `port_calls.STOPPED_KNOTS` | 0.5 | One definition of stopped, reused |

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Port centres | Done | `server.py` PORT_COORDS |
| Per vessel track query | Done, uses index `positions_mmsi_time` | `history.py` `track()` |
| Box and time aggregate queries | Done, pattern to follow | `history.py` `density()`, `activity_by_hour()` |
| Stop detection for a Statement of Facts | Exists, but cuts stops at 60 minute gaps | `port_calls.py` |
| Port name normalising | Done, strip and lower | `server.py` `_filter_text` |
| Haversine distance | Done | `server.py` `_haversine_nm` |
| Tool envelope and compact response | Done | `server.py` `_respond`, `_tidy` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| Board rules as pure functions | Medium | Edge cases at window boundaries |
| Three small history readers | Low | Query time, measured below |
| The tool and a residency cache | Low | Cache ageing must take an injected clock |
| A real data fixture from Port Dickson | Low | Choosing a window that contains every case |

**Maturity rating: 4/10.** Storage, identity, distances and the tool pattern all
exist, but the visit, window and classification rules that are the substance of
this story are new.

## 3. Guardrails that apply

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G2 | Run the command behind every checkable fact | Facts in this plan were checked on 2026-10-15; outputs quoted in section 2 and in the spec |
| G6 | Read the staged list before committing | The fixture is new; confirm nothing else rides along |
| G7 | Real sample before planning, committed as fixture | The fixture is captured from the production database, not invented |
| G8 | Derived values are marked or null | Distance, compass point, windows, hours in port and harbour craft are derived; flag is the existing derived flag; the response note says so |
| G9 | Output contract changes are a gate decision | No existing tool changes shape. This adds one tool. Changing `anchorages` and `port_calls` is written down as out of scope instead |
| G10 | Examine small gaps by name | One vessel of 104 is lost moving the stopped threshold from 0.8 to 0.5 kn; name it in build |
| G11 | Criteria assert values, not presence | Every criterion below names an input and the expected value |
| G15 | Say when a check ran once against varying conditions | The real data check is one capture of live traffic; recorded as such |
| G17 | Prove a guarding test can fail | Mutations listed in step 7 |
| G18 | Coverage claims checked by script | A script lists the public functions of `port_board.py` and checks each is named in a test |
| G19 | Normalise one input one way everywhere | The port argument goes through `_filter_text`, the same as `vessels_near_port`; destinations through one `normalise_destination` |
| G23 | Measure before fixing cost | Measured: 72 h box query 0.27 s, 14 day residency query 3.39 s on production, both full scans. Answer: cache residency, add no index |
| G24 | Report the cost of an addition | Report the tool schema growth in bytes alongside the response size |
| G26 | Unknown through every entry point | Null type, null destination, null SOG, the 102.3 sentinel, no earlier fix, no later fix, each driven through the rules and the tool |
| G27 | Clear bytecode between mutation runs | Applies to step 7 |
| G28 | Clock passed in, never read | Every rule takes `now`; the cache takes `now`; tests pin it to the fixture |
| G29 | Thresholds tested with literals | 6 h gap, 12 h heading in, 48 h departed, 10 of 14 days, 8 nm radius, each tested with literals either side and the constant asserted separately |

Not applicable: G1, G21 (no dependency change), G3, G4 (no package data file;
the port definition is Python), G12 (runbook written at close), G13, G14, G16,
G25 (no external connection; production is only read, never through aisstream),
G20 (no validation work), G22 (plan is new), G30 (no frontend in this repo).

## 4. Prerequisites

- [x] PRE-1: Confirm the current branch is not protected
- [x] PRE-2: Cut `feat/S26-port-dickson-board` from `main` (08262c3)
- [x] PRE-3: No retro carries forward: S25 has no story folder and M03's stories are closed

## 5. Implementation steps

### Step 1: Capture the Port Dickson fixture

**Files touched:** `tests/data/port_dickson_tracks.json` (new),
a capture script kept in the scratchpad, not the repository.

**What changes:** From a read only connection to the production database, export
84 hours of fixes for a chosen set of vessels, their identity rows, and their
per day presence inside 8 nm over 14 days. The set must contain at least: a
tanker stopped at port that declared Port Dickson; a ship stopped there that
declared somewhere else; a ship that left within 48 hours; a ship heading in
from outside the circle; a ship that crossed the circle without stopping; a tug;
a ferry. Record the capture moment in the file. Name the one vessel lost between
0.8 and 0.5 kn and say why it is acceptable (G10).

**How to check it worked:** a short script prints each required case and the
MMSI that fills it; the file is under 400 KB.

### Step 2: The rules, pure

**Files touched:** `maritime_mcp_server/port_board.py` (new),
`tests/test_port_board.py` (new).

**What changes:** Constants `RADIUS_NM`, `VISIT_GAP_HOURS = 6`,
`HEADING_IN_HOURS = 12`, `DEPARTED_HOURS = 48`, `AT_PORT_HOURS = 6`,
`RESIDENT_DAYS = 10` of `RESIDENT_WINDOW_DAYS = 14`, `LOOKBACK_HOURS = 72`.
`BOARD_PORTS` keyed like `PORT_COORDS`, holding radius and aliases.
`normalise_destination`, `matches_port`, `is_harbour_craft`, `residents`,
`visits`, `build_board(fixes_by_mmsi, identities, residents, centre, port, now)`.
No database, no clock reads. `STOPPED_KNOTS` and `SOG_UNAVAILABLE` imported from
`port_calls`.

**How to check it worked:** `pytest tests/test_port_board.py` passes, with the
cases in AC-1 to AC-8.

### Step 3: History readers

**Files touched:** `maritime_mcp_server/history.py`, `tests/test_history.py`.

**What changes:** `vessels_in_box(since, south, west, north, east)` returning the
distinct MMSIs; `days_present_in_box(since, ...)` returning MMSI to day count;
`identities(mmsis)` returning the identity rows; `destinations()` returning MMSI
and destination for every vessel that has one. Per vessel fixes reuse `track()`.

**How to check it worked:** new tests against a temporary database seeded with
literal rows.

### Step 4: The tool and the residency cache

**Files touched:** `maritime_mcp_server/server.py`, `tests/test_server.py`.

**What changes:** `port_board(port="port dickson")`. Normalises the port with
`_filter_text`; unknown port returns an error naming the available ones; no
history returns `source: unavailable` with four empty lists. Residency is
computed at most every 6 hours per port and kept in memory, ageing judged
against an injected `now`. Response: `data` (source, port, centre, radius_nm,
generated_at, feed live or snapshot, note), then `at_port`, `heading_in`,
`departed`, `harbour_craft`, each rounded through `_tidy`.

**How to check it worked:** tool tests in AC-9 pass; the existing loop over all
tools in `test_server.py` accepts the new one.

### Step 5: Real data check

**Files touched:** none in the repository.

**What changes:** Take a consistent copy of the production database with the
SQLite backup API, bring it to this machine, run the tool against it with
`now` pinned to the copy's newest fix, and paste the four lists.

**How to check it worked:** AC-10.

### Step 6: Cost

**Files touched:** none.

**What changes:** On the production copy, time the tool cold and warm, the
residency computation alone, and the response size. Measure the `list_tools`
payload before and after.

**How to check it worked:** AC-11, numbers pasted.

### Step 7: Mutations

**Files touched:** temporary edits, restored.

**What changes:** Each with `__pycache__` cleared before and after (G27):
`VISIT_GAP_HOURS` 6 to 1; alias match from exact to substring; silence counted
as departure; harbour craft type check removed; `RESIDENT_DAYS` 10 to 1.

**How to check it worked:** AC-13, each failing test named.

### Step 8: Verify

Run `verify.commands` and the coverage script.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | Each of the nine spellings seen in production (`MY PDI`, `PORT DICKSON`, `PORTDICKSON`, `MYPDI`, `MY_PDI`, `MY-PD`, `MLY PDI`, `MY_P.DICKSON`, `GHJUB>MYPDI`) matches Port Dickson, and `MYPKG`, `PORT KLANG`, `PDIX`, `SPDI`, an empty string and None do not. | [x] |
| AC-2 | Fixes inside the circle 5 h 59 m apart form one visit; 6 h 01 m apart form two. A fix outside the circle between two inside fixes also splits the visit. | [x] |
| AC-3 | A visit whose only slow fix is SOG 0.0 with status `Under way using engine` is stopped; one whose slowest fix is 0.5 is not; a SOG of 102.3 is ignored rather than read as a speed. | [x] |
| AC-4 | With a fix outside at 10:00 and the first inside at 10:50, the arrival window is 10:00 to 10:50. With no earlier fix in the lookback, the lower bound is null and the upper is 10:50. | [x] |
| AC-5 | With `now` at 20:00: a stopped visit last heard at 15:00 with no later fix is in `at_port`; last heard at 13:59 with no later fix is in `departed` with `silent` true and no left_by; a visit followed by an outside fix at 16:30 is in `departed` with left_by 16:30 and `silent` false. A stopped visit whose last fix inside was 47 h 59 m before `now` is listed; 48 h 01 m is not. (Reworded in build: the first wording put both cases outside 48 h.) | [x] |
| AC-6 | Type `Tug` is harbour craft; `Tanker` is not; a null type present on 10 of 14 days is harbour craft and on 9 of 14 is not; a `Tanker` present on 15 of 14 days is still not (residency decides only for null, `Other` and `Unknown type N`). Harbour craft never appear in `at_port` or `departed`. | [x] |
| AC-7 | A vessel crossing the circle at 12 kn that never drops under 0.5 kn and declared `SGSIN` appears in no list. The same track with destination `MY PDI` appears in `at_port` while inside. | [x] |
| AC-8 | A vessel with destination `MY PDI`, last fix 20 nm from the centre 3 h before `now`, is in `heading_in` with distance 20.0 nm; at 13 h before `now` it is not listed; inside the circle it is not in `heading_in`; a vessel in `departed` that still declares Port Dickson is not also in `heading_in`. | [x] |
| AC-9 | `port_board("  Port Dickson ")` returns the same board as `port_board("port dickson")`; `port_board("lumut")` returns an error naming `port dickson`; with no history the source is `unavailable` and all four lists are empty. The residency query runs once for two calls 5 h 59 m apart and twice for calls 6 h 01 m apart. | [x] |
| AC-10 | Against the production copy with `now` pinned: every `at_port` row has a fix within 8 nm in the last 6 h and a fix under 0.5 kn in its visit; RUBY and the Indomal ferries appear only in `harbour_craft`; the fixture test asserts the named vessel for each case listed in step 1. Checked once against one day's traffic (G15). | [x] |
| AC-11 | Warm tool time on the production copy is under 1.0 s and the cold residency computation time is reported; `list_tools` growth in bytes is reported next to the response size (G24). | [x] |
| AC-12 | `pytest` passes with more than 356 tests and the smoke test passes. A script confirms every public function in `port_board.py` is referenced in `tests/test_port_board.py` (G18). | [x] |
| AC-13 | Each mutation in step 7 fails at least one test, named in the build notes, and the suite is green again after restoring with caches cleared. | [x] |

All criteria are evaluable during build. Merging and deploying are deferred to
deliver; until then the evidence is the branch and the production copy (G5).

### Divergences found during build

- **Residency only for unknown types.** The fixture showed GOLDEN SPLENDOR, a
  tanker declaring `MY_PDI`, present on all 15 calendar days of the 14 day
  window. The planned rule would have hidden her as harbour craft. Residency
  now decides only when the type is null, `Other` or `Unknown type N`. AC-6
  updated.
- **Departed excludes heading in.** SHEN HUA 801 left about 3 hours before the
  capture and still declares `PORT DICKSON`. A vessel in `departed` is not also
  listed in `heading_in`. AC-8 updated.
- **A misspelling not matched.** MARIA PRINCESS declares `MYPID`. Not added as
  an alias, because matching typos invites false matches; she appears in
  `at_port` because she is inside the circle and stopped.
- **G10.** Moving from 0.8 to 0.5 kn loses one vessel of 104: MMSI 533000555,
  no identity ever received, slowest fix exactly 0.5 kn, no destination. It
  would not be a port call on any list, so the loss is acceptable.
- **Edge margin.** RAINA came in along the boundary, 7.9 nm then 8.0 then
  6.5, and the plain circle counted her out and back in within two minutes.
  Leaving now takes a fix beyond 9 nm (`EXIT_MARGIN_NM = 1.0`); a fix in the
  band carries a visit on but never opens one.
- **Departed means stopped.** The same flicker put RAINA in `departed` as
  well as `at_port`, because a visit counted if she declared the port even
  without stopping. Departures now require a stop. `at_port` still accepts a
  ship declaring the port that has not yet stopped.
- **An index after all.** The plan ruled out an index on a 0.27 s reading.
  That reading was a different query shape. The board's real candidate query,
  `SELECT DISTINCT mmsi ...`, took 2.05 to 2.27 s on production because the
  planner chose `positions_mmsi_time` and read every row through it. Measured
  options on a production copy: `NOT INDEXED` about 0.9 s and growing with
  retention; a covering index 0.04 s at 173 MB; `positions_time (observed_at)`
  named with `INDEXED BY` 0.07 s at 116 MB. Took the last. Build 2.0 s on first
  open; no existing history query slower, the anchorage density query 0.38 to
  0.10 s. The spec allowed this ("only if it is needed"); the plan's out of
  scope line was wrong and is removed.
- **A stale declared ETA.** CASTOR's `eta_declared` read `25-09 06:30` on
  15 October. Passed through as typed, which is correct for the server; the
  dashboard should mark an ETA that looks past. Not changed here.
- **README tool table is stale.** It lists 3 of 15 tools and an old port list.
  One row added for `port_board` as planned; the rest written down, not fixed.
- **Residency counts calendar days.** Distinct UTC dates with a fix inside the
  port's box between `now` minus 14 days and `now`, which can reach 15. The box
  is the square around the circle, because SQLite here has no trigonometry.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `maritime_mcp_server/port_board.py` | Port definitions and the board rules, pure |
| `tests/test_port_board.py` | Rules tests, synthetic and fixture |
| `tests/data/port_dickson_tracks.json` | Real fixes from production around Port Dickson |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/history.py` | Four readers; `positions_time` index in the schema |
| `maritime_mcp_server/server.py` | `port_board` tool, residency cache |
| `tests/test_history.py` | Reader tests |
| `tests/test_server.py` | Tool tests |
| `README.md` | One entry in the tool list |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| The 3.4 s residency query blocks the single server process when it runs | Certain, every 6 h | Live map pauses once for about 3 s | Cache 6 h; measure on the copy; if it bites, move the cache refresh off the request path in a later story |
| A window boundary off by one minute moves a ship between lists | Medium | Wrong list | Literal tests either side of every threshold (G29) |
| The fixture's window lacks one of the required cases | Medium | Untested case | Step 1 prints each case and its MMSI before any code |
| Destination spellings not yet seen | Certain over time | A ship heading in is missed | Unmatched ships still appear in `at_port` once inside; aliases are one tuple |
| `Passenger` hides a rare cruise call as harbour craft | Low | One call misfiled | Accepted for now; recorded |

## 9. Out of scope

- The dashboard page. Different repository, separate work, reads this tool.
- Changing `anchorages` to judge by speed, and retuning `port_calls` gaps for
  sparse coverage. Both change existing tool output (G9). Written into M04.
- More ports. The table takes them; Kuala Linggi is the obvious next one.
- Bringing the README tool table up to date. Stale before this story.
- Flagging a declared ETA that is already past. A dashboard concern.

## 10. Verification

```
.venv/bin/python -m pytest
.venv/bin/python -m maritime_mcp_server.smoke_test
```

**Result:** run 2026-10-16 on `feat/S26-port-dickson-board`, uncommitted.

```
$ .venv/bin/python -m pytest
441 passed in 0.79s
$ .venv/bin/python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

Baseline before the story: 356 passed. Coverage script (G18): 9 public
functions in `port_board.py`, 0 missing from `tests/test_port_board.py`.

Real data, production copy taken 2026-10-15 16:08 UTC with the SQLite backup
API, `now` pinned to its newest fix, checked once against one day's traffic
(G15):

- at_port 5: ROXANNE, GERASIMOS, RAINA, MARIA PRINCESS, GOLDEN SPLENDOR.
  Every row within 8 nm, heard within 6 h, stopped.
- heading_in 1: CASTOR, 137.3 nm, declared MY PDI.
- departed 6: SHEN HUA 801 and DIMITRI and GAS FAIRWAY with a later fix
  outside; ORKIM DISCOVERY, ORKIM GLORY and 533132158 silent.
- harbour_craft 10: RUBY, INDOMAL REGAL, six tugs, two sailing vessels.
  INDOMAL DYNASTY, INDOMAL IMPERIAL and MAJESTIC KAWANUA were not heard inside
  in the last 6 h and appear in no list, never in at_port or departed.

Cost (G23, G24), same copy: index build 2.0 s and 116 MB once; board cold
0.49 s, warm 0.13 s; residency alone 0.079 s; response 7,165 bytes per call;
`list_tools` 16,552 to 17,500 bytes, 948 more per session for every client.

Mutations (G17, G27), caches cleared before and after each, suite 441 green
after restoring:

| Mutation | Failing tests, by name |
|----------|------------------------|
| `VISIT_GAP_HOURS` 6 to 1 | test_fixes_5h59_apart_are_one_visit, test_last_heard_5h_ago_with_nothing_since_is_still_at_port, test_the_real_capture_puts_each_vessel_in_its_list[DIMITRI], and 5 more |
| alias match exact to substring | test_near_misses_and_blanks_do_not[SPDI], [PDIX] |
| silence counted as departure | test_last_heard_6h01_ago_with_nothing_since_has_gone_quiet_not_departed, test_in_the_real_capture_orkim_discovery_went_quiet_and_dimitri_sailed |
| harbour craft type check removed | test_a_tug_is_harbour_craft_and_a_tanker_is_not, test_harbour_craft_never_reach_the_port_call_lists, real capture [RUBY], [INDOMAL REGAL], and 3 more |
| `RESIDENT_DAYS` 10 to 1 | test_residency_decides_for_an_unknown_type_at_ten_days_not_nine, real capture [533133187], and 4 more |
| `EXIT_MARGIN_NM` 1.0 to 0 | test_leaving_takes_a_fix_past_9nm_and_8_9_is_not_enough, test_a_ship_working_along_the_edge_is_one_visit_not_two |
