---
pipeline_state:
  story_id: S09
  milestone: M01
  title: All Malaysian waters, and ports to name them by
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: feat/S09-all-malaysian-waters
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S09: All Malaysian waters, and ports to name them by

## 1. What this is

The server claims to cover Malaysian waters. It covers half of them.

```python
DEFAULT_BOX = [[[0.5, 98.5], [7.5, 105.5]]]
```

That stops at 105.5 degrees east. Sabah and Sarawak start around 109 and run to
119. Kuching, Bintulu, Miri, Labuan, Kota Kinabalu and Sandakan have never been
inside the subscription, so no vessel there has ever been requested, let alone
received. The comment above the constant says "the Strait of Malacca and both
coasts of the peninsula", which is accurate; the README's claim of Malaysian
waters is not.

The port table has the same gap. Five ports, all peninsular.

## 2. Evidence

Per G2, measured rather than assumed.

**Widening the box does find vessels.** Four minutes of live feed with the box
extended to 119.5E, counting distinct vessels within 30 nm of each port:

```
  Tanjung Pelepas        86        Kuching                 0
  Singapore (ref)        86        Bintulu                 0
  Port Dickson           19        Miri                    0
  Malacca                 5        Labuan                  0
  Kota Kinabalu           5        Sandakan                0
  Port Klang              0        Kuantan                 0
  Penang                  0        Langkawi                0

  vessels east of 105.5E, previously never requested: 5
```

**An earlier measurement in this project was wrong and is corrected here.** A
probe reported "Bintulu: 0 vessels" while the subscription box excluded Bintulu
entirely. That number measured nothing. It is the same mistake G2 exists to
prevent, made inside a check rather than inside a plan.

**Widening without ports would manufacture a labelling bug.** With the current
five ports, an East Malaysian vessel takes the nearest peninsular name:

```
  Kota Kinabalu    would be labelled Tanjung Pelepas      800 nm away
  Sandakan         would be labelled Tanjung Pelepas      914 nm away
  Bintulu          would be labelled Tanjung Pelepas      582 nm away
  Kuching          would be labelled Tanjung Pelepas      408 nm away
```

S06 existed because a vessel 38 nm from a port was labelled as if it were at
it. Shipping the box change alone would reintroduce that at twenty times the
distance. The two changes are one story for that reason.

## 3. What this story does not do

Stated plainly because the title oversells it.

Port Klang, Penang, Langkawi, Kuantan, Kuching, Bintulu, Miri and Sandakan
return nothing today and will still return nothing after this story. There is no
receiver near them in the aisstream network. No bounding box change invents
coverage; it only stops the server from refusing to ask.

The gain is Kota Kinabalu, roughly five vessels, plus a port vocabulary that
stays correct as coverage grows, whether that comes from a future receiver or a
paid feed.

## 4. Scope

In scope:

1. Widen `DEFAULT_BOX` to cover Sabah and Sarawak.
2. Add the missing Malaysian commercial ports to `PORT_COORDS`.
3. Correct the comment and the README where they overclaim.

Out of scope (F5):

- Any second bounding box, or per-region subscriptions.
- A distance cutoff on nearest port. S06 decided against one and nothing here
  changes that reasoning: the distance is reported, so the caller judges.
- Non-Malaysian ports, including Singapore, despite it being where much of the
  traffic actually is. Naming it would be correct but is a scope decision, not a
  side effect of this one.

## 5. Contract decision (G9)

No field changes shape. Two behaviours change.

**More vessels may be returned**, from water the server previously never
subscribed to. A caller that assumed the fleet was peninsular would be surprised.

**`nearest_port` gains new possible values.** Any caller matching on the five
known names, rather than treating it as free text, would need updating. Inside
this repository nothing does; `vessels_near_port` resolves its argument against
`PORT_COORDS` itself, so it gains the new ports automatically.

## 6. Acceptance criteria

1. `DEFAULT_BOX` covers 119.5E, and a test asserts Kota Kinabalu, Sandakan,
   Bintulu, Kuching, Miri and Labuan all fall inside it.
2. The same test asserts the previous box excluded them, so the change is pinned
   to the reason for it rather than to a number.
3. `PORT_COORDS` contains each added port, and a coordinate check places each
   within 15 nm of its real position.
4. A vessel off Kota Kinabalu resolves to Kota Kinabalu, not Tanjung Pelepas.
5. A vessel off Port Klang still resolves to Port Klang, so peninsular
   behaviour is unchanged.
6. `vessels_near_port("Kota Kinabalu", ...)` resolves, proving the tool picks up
   new ports without separate wiring.
7. The collector still subscribes with exactly one bounding box.
8. `pytest` passes with no skips introduced.
9. `smoke_test` still ends with `All smoke checks passed.`
10. The README no longer claims coverage the feed does not provide, and says
    which ports return nothing today.

## 7. Risks

| Risk | Handling |
|---|---|
| A larger box raises message volume beyond what the store or the free tier handles | Measured: 5 extra vessels over 4 minutes. If it ever matters, the prune loop and the 30 minute window already bound the store |
| Callers matching on the five old port names break | Named in the G9 note; nothing in this repository does it |
| Adding ports changes existing peninsular answers | Criterion 5 pins Port Klang explicitly |
| The wider box implies coverage that does not exist | Criterion 10, and the README says plainly which ports are empty |

## 8. Verify

```
$ .venv/bin/python -m pytest
201 passed

$ .venv/bin/python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

193 before this story, 201 after, no skips.

### A timing scare that was not one

The suite reported 8.63s where earlier stories reported under a second, which
looked like a regression this story had caused. It had not. Measured with the
work stashed, `main` alone is slower:

```
  with S09:     import server 3.34s   full suite 8.78s
  main, S09 stashed: import server 5.04s   full suite 19.19s
```

The slowest individual test is 0.09s and every test together is well under a
second, so the time is import and collection, dominated by the `mcp` SDK, and it
varies with machine load. Recorded here because the obvious move was to go
hunting for a regression in the wrong story.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | Box reaches Sabah and Sarawak | yes | `test_the_box_reaches_sabah_and_sarawak` |
| 2 | The old box excluded them, pinned | yes | `test_the_previous_box_excluded_all_of_them` |
| 3 | Port coordinates are in Malaysian waters | yes | `test_every_port_coordinate_is_in_malaysian_waters` |
| 4 | A Kota Kinabalu vessel resolves to Kota Kinabalu | yes | `test_an_east_malaysian_vessel_gets_an_east_malaysian_port`, within 15 nm |
| 5 | Peninsular answers unchanged | yes | `test_the_peninsula_still_answers_the_same` |
| 6 | `vessels_near_port` picks up new ports | yes | `test_vessels_near_port_picks_up_a_new_port_without_separate_wiring` |
| 7 | Still exactly one bounding box | yes | `test_there_is_still_exactly_one_bounding_box` |
| 8 | pytest passes, no new skips | yes | 201 passed |
| 9 | smoke test passes | yes | above |
| 10 | README no longer overclaims | yes | it now prints the per-port measurement and says Port Klang returns nothing |

Ports went from 5 to 20: six on the west coast, six south and east, four in
Sarawak, four in Sabah and Labuan.
