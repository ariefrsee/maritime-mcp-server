---
pipeline_state:
  story_id: S08
  milestone: M01
  title: Which way a vessel is pointing
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: feat/S08-course-and-heading
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S08: Which way a vessel is pointing

## 1. What this is

AIS transmits which way a ship is going. This server drops it.

`position_fields` maps latitude, longitude, speed and status, and nothing else.
So a consumer can say a vessel is doing 16 knots but cannot say in which
direction, and a chart symbol cannot be oriented. Every vessel on a map drawn
from this data points north, which is wrong for all but a few of them.

Two fields carry the answer and they are not the same thing. **Course over
ground** is the direction the vessel is actually travelling. **True heading** is
where the bow is pointing, which differs in a current or a crosswind and is what
a chart symbol conventionally shows. Both are reported; this story carries both
and lets the consumer choose.

## 2. Evidence

Per G2, from a 70 second sample of the live feed:

```
messages carrying Cog: 44
  usable COG: 43   sentinel (>=360): 1
  sample COG: [0, 0, 9.6, 10.9, 28, 30.8, 35.4, 40]
  usable heading: 37   sentinel (511): 7
  sample heading: [21, 30, 31, 44, 44, 45, 54, 75]
```

Two things follow. Course is almost always present, heading noticeably less
often, so a consumer that wants one value should prefer heading and fall back to
course rather than depending on either alone. And the sentinels are real and
occur in ordinary traffic, not just in the one message captured for S06.

**The guards already exist.** S06 added `course_over_ground()` and
`true_heading()` to `ais_mapping`, with tests, and deliberately did not map
either into a record:

```
$ grep -n "course_over_ground\|true_heading" maritime_mcp_server/ais_mapping.py
246:def course_over_ground(cog):
255:def true_heading(heading):
```

S06's plan named this exact story as the out-of-scope follow-up. So this is
wiring that already-tested translation into the record, not new logic.

## 3. Scope

In scope:

1. `course_degrees` and `heading_degrees` in the record, via the existing guards.
2. Both persisted to history, so a stored track can be drawn oriented.
3. Both returned by `vessel_track`.
4. Tests, including against the S06 sentinel fixture.

Out of scope, written down rather than built (F5):

- Deriving a course from consecutive positions when AIS reports none. That is
  inference, and inventing a heading is exactly what G8 forbids. A vessel with
  no reported course has none.
- Rotating anything. The dashboard draws; this story only supplies the number.
- Magnetic variation, rate of turn, any other AIS field.

## 4. Contract decision (G9)

Two fields are added to every record, and two columns to the `positions` table.
Both are additive: no existing field changes meaning, and no caller that ignores
them is affected.

`vessel_track` gains the same two fields per point, which is additive to a tool
added in S07 and not yet relied on by anything but the dashboard.

A note on honesty, because it is the whole point of G8: a vessel that does not
report a course gets `null`, not `0`. Zero degrees is due north, a real and
common heading, and defaulting to it would put a fleet of ships pointing north
that never said any such thing. This is the same failure as the speed sentinel
in S06, and it is why the guards were written first.

## 5. Acceptance criteria

Each evaluable at build or verify (G5).

1. A position message with `Cog` 87.5 produces `course_degrees` 87.5.
2. A position message with `TrueHeading` 90 produces `heading_degrees` 90.
3. The sentinels map to `None`: `Cog` 360, `TrueHeading` 511.
4. Absent fields produce `None`, never `0`.
5. Course 0 and heading 0 survive as 0, being due north rather than missing.
6. Both are written to `positions` and returned by `vessel_track`.
7. A restored vessel carries both through rehydrate.
8. Asserted against the real S06 sentinel fixture, not only built input.
9. `pytest` passes with no skips introduced.
10. `smoke_test` still ends with `All smoke checks passed.`

## 6. Risks

| Risk | Handling |
|---|---|
| An existing database has no such columns and the server fails on open | Additive migration on startup, checked by a test that opens a schema built without them |
| Callers read 0 as north when the value is missing | Null, never 0, and criteria 4 and 5 pin both directions |
| Class B reports carry these fields differently | The existing fixture has both message types; criterion 8 runs over it |

## 7. Verify

```
$ .venv/bin/python -m pytest
193 passed in 0.47s
```

186 before this story, 193 after, no skips.

```
$ .venv/bin/python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

Live, through a real MCP client over stdio:

```
vessels: 32   with course: 31   with heading: 29
of 16 moving vessels, 16 report a course

  MORNING PILOT             14.5 kn  course  67.4  heading 68
  CSM HYDRA                    7 kn  course 295.4  heading 297
  PILOT 16                  12.5 kn  course  94.1  heading 94
  KONA                      11.8 kn  course 322.6  heading 324
```

Every moving vessel reports a course. Course and heading differ by a degree or
two on most of them, which is set and drift and is exactly why both are carried
rather than one being treated as the other.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | Cog 87.5 becomes course_degrees 87.5 | yes | `test_course_and_heading_are_recorded` |
| 2 | TrueHeading 90 becomes heading_degrees 90 | yes | same |
| 3 | Sentinels 360 and 511 become None | yes | `test_the_course_and_heading_sentinels_are_stored_as_nothing` |
| 4 | Absent fields are None, never 0 | yes | `test_a_missing_course_is_null_and_not_north` |
| 5 | Course 0 and heading 0 survive as 0 | yes | `test_due_north_survives_as_zero` |
| 6 | Written to positions, returned by vessel_track | yes | `test_course_and_heading_are_recorded` reads them back through `track()` |
| 7 | Carried through rehydrate | yes | `test_a_restored_vessel_keeps_its_course` |
| 8 | Asserted against the real sentinel fixture | yes | `test_the_real_sentinel_fixture_yields_no_course` |
| 9 | pytest passes, no new skips | yes | 193 passed |
| 10 | smoke test passes | yes | above |

### The contract pins that had to move

Three existing tests asserted an exact record key set and failed, which is the
G9 guard doing its job rather than a defect: `test_a_record_has_exactly_the_
snapshot_keys`, `test_position_fields_extracts_only_the_position_half` and
`test_every_fixture_record_has_the_full_key_set`. The plan declared this
additive change and the user approved it, so the pins were updated to the
approved shape rather than the change being softened to avoid them.

### Migration

An additive migration runs on open, covered by
`test_a_database_written_before_these_columns_still_opens`, which builds a
pre-S08 schema by hand, inserts a row, and checks the row survives and reports
no course rather than the query failing.
