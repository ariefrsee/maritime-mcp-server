---
pipeline_state:
  story_id: S12
  milestone: M01
  title: AIS not-available sentinels, and how far the nearest port actually is
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: fix/S06-ais-sentinels-and-port-distance   # branch keeps its original name
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S06: AIS not-available sentinels, and how far the nearest port actually is

## 1. What this is

Two reporting bugs, both of the same shape: the server states something as a
fact that the feed did not support. Both were found while building a dashboard
on top of this server, not by reading code.

**Speed.** AIS encodes speed over ground in 0.1-knot steps, where the value 1023
means "not available". Scaled, that arrives as `102.3`. `position_fields` passes
`Sog` straight through, so a vessel that did not report its speed is published as
travelling at 102.3 knots. A consumer sorting a fleet by speed puts that vessel
at the top, which is exactly how it surfaced.

**Nearest port.** `_nearest_port` returns the closest of five hardcoded ports
with no distance limit, so it always names one. Measured against 230 live
vessels, the median vessel is 19.5 nm from the port it is labelled with and the
furthest is 37.9 nm. The value is not wrong, but "Tanjung Pelepas" reads as
"at Tanjung Pelepas", and nothing in the response says otherwise.

Both are direct instances of G8: a derived or missing value presented as a
measured one.

## 2. Evidence

Per G2, everything below was produced by running a command, not from memory.

### The sentinel is real, and is not in the existing fixture

The committed fixture does not contain it, so it could not have caught this:

```
$ .venv/bin/python -c "...count Sog values in tests/data/ais_capture.json..."
messages in fixture: 199
messages carrying Sog: 179
Sog == 102.3 (the not-available sentinel): 0
Sog > 102.2: 0
```

Per G7, a real sample was captured from the live feed rather than planned from
the specification:

```
$ .venv/bin/python capture_sentinel.py
  captured sentinel Sog=102.3 from PositionReport (1/6)
167 messages seen, 1 carrying the sentinel

MessageType: PositionReport
Sog: 102.3  Cog: 360  TrueHeading: 511
NavigationalStatus: 0
MMSI: 563070140  name: 'PSA TAURUS YS52     '
```

That one message carries **three** not-available sentinels, not one:

| Field | Sentinel | Meaning |
|---|---|---|
| `Sog` | `102.3` (raw 1023) | speed over ground not available |
| `Cog` | `360` (raw 3600) | course over ground not available |
| `TrueHeading` | `511` | heading not available |

Only `Sog` reaches a record today. `Cog` and `TrueHeading` are not mapped, so
they are not currently bugs, but they are the same trap if anyone maps them
later.

### The port distance is real

Measured against the live feed through the dashboard, 230 vessels:

```
nearestPort distribution:  Tanjung Pelepas 205, Malacca 15, Port Klang 10
distance to that port (nm):  min 7.7   median 19.5   max 37.9
vessels further than 30nm from any listed port: 21
```

## 3. Scope

In scope:

1. Clear the three AIS not-available sentinels at the point AIS is decoded.
2. Report how far away the nearest port is, alongside its name.
3. Tests for both, against the captured sample.

Out of scope, written down rather than built (F5):

- Mapping `Cog` or `TrueHeading` into the record. Guarding them is in scope so
  the trap is closed; exposing them is a separate story.
- Changing the port list, or adding a port lookup by distance.
- Anything in the dashboard repository.

## 4. The contract decision (G9)

G9 says a change to an output contract is a gate decision, not a build decision.
This story changes the contract in two ways, and both are recorded here so the
decision is visible rather than discovered in a build report.

**Change 1, `speed_knots` may now be `null` where it was previously a number.**
This is a correction, not a regression: the number it replaces was false. Any
consumer already has to handle `null`, because `speed_knots` is `None` whenever
a vessel has been seen only through static data.

**Change 2, records gain a `nearest_port_nm` field.** Additive, so existing
consumers are unaffected. The alternative considered was returning `None` for
`nearest_port` beyond some cutoff, which was rejected: any cutoff is arbitrary,
and it destroys information rather than qualifying it. Reporting the distance
lets the caller decide what counts as near, which is what G8 asks for when a
value is derived rather than transmitted.

## 5. Acceptance criteria

Each is evaluable during build or verify (G5). None depends on a commit.

1. `position_fields` maps `Sog` of 102.3 to `None`, and any value above 102.2 or
   below 0 to `None`.
2. `position_fields` leaves valid speeds untouched, including 0 and 102.2.
3. A test asserts 1 and 2 against the newly committed real sample.
4. `Cog` of 360 and `TrueHeading` of 511 are recognised as not-available by a
   shared helper, proven by a test, even though neither is mapped into a record.
5. `_nearest_port` returns the distance alongside the name.
6. Records carry `nearest_port_nm`, rounded to one decimal, `None` exactly when
   `nearest_port` is `None`.
7. The captured sentinel sample is committed under `tests/data/`.
8. `.venv/bin/python -m pytest` passes with no skips introduced by this story.
9. `.venv/bin/python -m maritime_mcp_server.smoke_test` ends with
   `All smoke checks passed.`

## 6. Risks

| Risk | Handling |
|---|---|
| The smoke test or an existing test asserts on the exact record shape and breaks on the new key | Run the suite before changing anything, so a failure afterwards is attributable |
| A consumer treats `speed_knots: null` as zero | Out of this repository's control; noted in the retro. The bundled snapshot already contains nulls |
| 102.2 is a legitimate speed and gets clipped | The cutoff is above 102.2, not at it. Criterion 2 covers it |

## 7. Verify

Both commands from `verify.commands`, run on this branch (F4).

```
$ .venv/bin/python -m pytest
158 passed in 0.69s
```

140 before this story, 158 after. No skips introduced.

```
$ .venv/bin/python -m maritime_mcp_server.smoke_test
vessels_near_port(Port Klang, 30nm) -> [snapshot] 5 vessel(s), nearest Bunga Mas Lima at 0.1nm
vessel_details('Kowloon Express') -> MMSI 477055221, flag Hong Kong
vessels://all -> [snapshot] 18 vessel(s)

All smoke checks passed.
```

Against the live feed, through a real MCP client over stdio:

```
source: live  vessels: 44
carrying nearest_port_nm: 44 of 44
  distance nm: min 15.4 median 21.7 max 35.7

  STRAITS ORACLE         Tanjung Pelepas    21.7 nm   speed=2.8
  HAWKS MAJESTY          Tanjung Pelepas    16.9 nm   speed=0.1
  DESH SURAKSHA          Tanjung Pelepas    22.8 nm   speed=0
  MANILA MAERSK          Tanjung Pelepas    15.4 nm   speed=0

records with an impossible speed: 0
records where name and distance disagree about being null: 0
```

Before this story the same fleet reported a vessel at 102.3 knots.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | `Sog` 102.3, above 102.2, or below 0 becomes `None` | yes | `test_speed_sentinel_becomes_none`, `test_negative_speed_is_rejected` |
| 2 | Valid speeds untouched, including 0 and 102.2 | yes | `test_speed_just_below_the_sentinel_is_kept`, `test_zero_speed_is_kept_and_not_confused_with_missing` |
| 3 | Asserted against the real sample | yes | `test_real_sentinel_message_yields_no_speed` |
| 4 | `Cog` 360 and `TrueHeading` 511 recognised, though unmapped | yes | `test_course_sentinel_becomes_none`, `test_heading_sentinel_becomes_none` |
| 5 | `_nearest_port` returns the distance with the name | yes | `test_nearest_port_reports_the_distance_with_the_name` |
| 6 | `nearest_port_nm` present, `None` exactly when the name is | yes | `test_port_name_and_distance_are_null_together_and_never_apart`, and 0 mismatches across 44 live records |
| 7 | Captured sample committed under `tests/data/` | yes | `tests/data/ais_not_available_sentinels.json` |
| 8 | `pytest` passes, no new skips | yes | 158 passed |
| 9 | Smoke test ends with `All smoke checks passed.` | yes | above |

### Follow-ups, not built here (F5)

- The dashboard does not yet surface `nearest_port_nm`. It is carried by the
  server now; displaying "Tanjung Pelepas, 21.7 nm" is a change in that repo.
- `config.json` records `project.root` as `/Users/ariefrse/maritime-mcp-server`,
  which is not where this checkout lives. Stale, and unrelated to this story.
