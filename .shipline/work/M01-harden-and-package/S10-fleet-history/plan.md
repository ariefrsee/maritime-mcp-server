---
pipeline_state:
  story_id: S10
  milestone: M01
  title: The fleet, as it was
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: feat/S10-fleet-history
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S10: The fleet, as it was

## 1. What this is

S07 gave the server a memory and S08 gave it direction, but only one question
can be asked of that memory: `vessel_track` returns one vessel. There is no way
to ask what the whole strait looked like an hour ago.

That blocks the next useful thing, which is playback: scrubbing back through
stored history and watching traffic move. Playback also happens to be how you
check an event detector's work, so it earns its place twice before the port call
log is written.

Asking 250 times, once per vessel, is not an answer.

## 2. Evidence

Per G2, from the database the running dashboard has been filling:

```
positions stored: 5696
distinct vessels: 451
span: 2026-09-15T03:02:15 -> 2026-09-15T05:27:10
positions per vessel: median 7  max 98
rows in the last 6 hours: 5696  (~389 KB as JSON)
```

Two things follow.

**One request is affordable.** Roughly 390 KB for six hours of the whole fleet,
fetched once and scrubbed locally, beats 250 round trips by a wide margin.

**The median vessel has 7 positions.** Playback cannot assume a dense track. A
vessel with two fixes an hour apart is a straight line between two real
observations and nothing more, and the tool must not imply otherwise.

## 3. Scope

In scope:

1. `fleet_track(hours)`, returning every vessel's positions in the window,
   grouped by MMSI, with identity attached.
2. A cap on the window and on rows returned, so a large database cannot produce
   a response nothing can hold.
3. Tests.

Out of scope (F5):

- Interpolating between fixes. The tool returns observations; whoever draws them
  decides how to join them, and says so.
- Any rendering, slider, or playback UI. That is a dashboard story.
- Server-side downsampling. Worth doing when a measurement says so, not before.

## 4. Contract decision (G9)

`fleet_track` is a new tool. Nothing existing changes shape.

Its response states `truncated` when the cap was hit, rather than silently
returning less than was asked for. A playback that quietly drops half the fleet
would look like vessels vanishing.

## 5. Acceptance criteria

1. `fleet_track(hours)` returns positions for every vessel with history in the
   window, grouped by MMSI.
2. Each vessel carries its name, type and flag where known, so a caller need not
   join against another tool.
3. Positions within a vessel are oldest first.
4. A vessel with no history in the window is absent, not present and empty.
5. The window is clamped to the retention period, and `hours` below zero is
   treated as zero rather than returning everything.
6. Beyond the row cap the response sets `truncated: true` and says what the cap
   was.
7. The note states that gaps between fixes are real and nothing is interpolated.
8. An empty database returns an empty result and no error.
9. `pytest` passes with no skips introduced.
10. `smoke_test` still ends with `All smoke checks passed.`

## 6. Risks

| Risk | Handling |
|---|---|
| A long window returns more than a client can hold | Row cap plus an explicit `truncated` flag, criterion 6 |
| Callers assume a dense track and draw smooth motion | The median vessel has 7 fixes; criterion 7 puts the warning in the payload |
| The query is slow on a large table | The existing `(mmsi, observed_at)` index covers it; if a measurement later says otherwise, say so rather than guessing now |

## 7. Verify

```
$ .venv/bin/python -m pytest
213 passed in 0.62s

$ .venv/bin/python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

201 before this story, 213 after, no skips.

Live, through a real MCP client against the database the dashboard has filled:

```
query took 0.25s, payload 1202 KB
vessels 453, positions 5803, truncated False
busiest: PSA MARVEL CS05 with 98 positions
first fix: 03:03:10  last: 05:26:10
```

### The payload estimate was wrong by three times

The plan predicted "~389 KB as JSON" for six hours, from 5696 rows at an assumed
70 bytes each. The real payload is 1202 KB, about 210 bytes a row. The estimate
ignored that every row repeats its field names and that identity is joined in.

It does not change the design: one 1.2 MB request still beats 250 round trips,
and the query runs in a quarter of a second. It does change the default the
dashboard should ask for, which is a shorter window rather than six hours.

Recorded rather than quietly corrected, because an unchecked arithmetic estimate
in a plan is exactly what G2 is about, and this one was mine.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | Grouped by MMSI across the fleet | yes | `test_fleet_track_groups_positions_by_vessel` |
| 2 | Identity attached, no second lookup | yes | `test_fleet_track_carries_identity_so_no_second_lookup_is_needed` |
| 3 | Oldest first within a vessel | yes | `test_fleet_track_orders_each_vessel_oldest_first` |
| 4 | A vessel with no history is absent, not empty | yes | `test_a_vessel_with_no_history_in_the_window_is_absent` |
| 5 | Window clamped, negative means zero | yes | `test_fleet_track_clamps_a_negative_window_to_nothing`, `..._beyond_retention` |
| 6 | Truncation is stated, not silent | yes | `test_fleet_track_reports_when_it_hit_the_cap`, `..._flags_truncation_in_the_payload` |
| 7 | The note says gaps are real | yes | `test_fleet_track_states_that_gaps_are_real` |
| 8 | Empty database is empty, not an error | yes | `test_fleet_track_on_an_empty_database_is_empty_not_an_error` |
| 9 | pytest passes, no new skips | yes | 213 passed |
| 10 | smoke test passes | yes | above |

### Follow-up, not built here (F5)

Server-side downsampling. The plan said to do it when a measurement asked for
it. This measurement says 1.2 MB for six hours, which is workable but heavy on a
phone. The cheaper first move is a shorter default window in the client, which
is a dashboard decision.
