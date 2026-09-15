---
pipeline_state:
  story_id: S07
  milestone: M02
  title: Compact responses
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S07-compact-responses
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19, G20, G21, G22]
---

# S07: Compact responses

## 1. What this is

Asking where the ships are currently costs about 6,700 tokens. Ask three
questions and a meaningful slice of the conversation has been spent on JSON that
Claude reads once, summarises in a sentence, and never looks at again.

Nothing about the answer changes. The ships are the same ships, the provenance
block stays, and an unknown value is still never dressed up as a known one. What
changes is that the same answer is written down in a fraction of the space, and
that no single question can return an unbounded amount of it.

This is the flaw specific to building for a model rather than a screen. A web
app paginates because a person cannot read 67 rows. Nobody paginates for a model,
and the cost lands as context rather than scroll.

## 2. Maturity assessment

Nothing exists, but the investigation is unusually complete: every number below
was measured before the plan was written, and the savings were measured
cumulatively rather than estimated.

### Where the cost actually is

`vessels_near_port("Tanjung Pelepas", 40)` against the committed fixture, 67
vessels:

| Measure | Value |
|---------|-------|
| Response | 26,713 characters, roughly 6,678 tokens |
| Per vessel | 398 characters |
| **Pure indentation** | **7,683 characters, 29% of the whole** |
| Null fields | 172 of 871, 19%, carrying no information |
| `nearest_port` | 8%, and identical for every vessel when you asked about one port |
| `position_age_seconds` | 7%, per vessel, when the provenance block already carries the oldest |
| `lat` and `lon` | 12% combined, at full float precision such as `1.2196916666666666` |

### What each fix is worth, measured not guessed

Applied cumulatively to the same response:

| Change | Result | Saved |
|--------|--------|-------|
| as shipped, `indent=2` | 26,713 chars | |
| compact separators | 19,030 | 28% |
| drop null fields | 16,337 | 10% |
| round `lat`/`lon` to 4 decimals, about 11 metres | 15,053 | 4% |
| drop per vessel age | 13,110 | 7% |
| drop `nearest_port` when the query named a port | 10,899 | 8% |
| **cumulative** | **10,899 chars, ~2,724 tokens** | **60%** |

**None of that changes what the tool returns.** It is the same vessels with the
same facts, written down more carefully. The structural work, capping results and
offering a summary, comes on top.

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Three tools returning `json.dumps(..., indent=2)` | the 29% | `server.py` |
| `to_record` producing all eleven keys, nulls included | S02's promise, and 19% of the payload | `ais_mapping.py` |
| `_nearest_port` computed per vessel per call | 8%, and redundant in the near-port case | `server.py` |
| Provenance block with `oldest_position_age_seconds` | already carries the summary the per vessel field duplicates | `server.py` |
| 157 tests | several assert on parsed output, so they should survive; some assert counts and key sets | `tests/` |
| `tools/compare_wire.py` | captures eleven responses, so before and after can be diffed and sized | `tools/` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| Compact serialisation | trivial | low |
| Coordinate rounding | trivial | low, 4 decimals is about 11 metres |
| Dropping redundant per vessel fields | low | low |
| Dropping null fields | low | **medium. This weakens a promise S02 made** |
| A cap on how many vessels one call returns | medium | medium, a cap that silently truncates is worse than a large response |
| A summary mode, counts and the nearest few, with detail on request | medium | medium, it changes what the tools return |

**Maturity rating: 6/10.** Nothing is built, but the problem is measured to the
character, the cheap wins are proven, and a wire capture tool already exists to
verify that nothing else moved.

## 3. Guardrails that apply

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G2 | Never write a checkable fact into a plan without running the command that checks it | Every number in section 2 was measured against the committed fixture before this plan was written |
| G8 | Never present data in a field the source did not supply | The load bearing one. Rounding a coordinate is fine; implying a vessel reported a type it never sent is not. This is why dropping nulls needs a decision rather than a shrug |
| G9 | A change to an output contract is a gate decision, not a build decision | **This story changes every response.** Dropping nulls and capping results are both contract changes and both go to the gate |
| G11 | A criterion that checks shape must not stand in for one that checks behaviour | Criteria name measured sizes and specific fields, not "responses are smaller" |
| G15 | Say when a criterion was verified once against conditions that vary | All measurements come from one 89 vessel fixture. A busy live store behaves differently and that must be stated |
| G17 | Prove a test can fail before trusting that it passes | The size assertions must be shown to fail against the current code |
| G19 | Normalise the same input the same way everywhere | Whatever record shaping is chosen must apply identically across all three tools and the resource, not just the one being optimised |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected
- [ ] PRE-2: Cut `feat/S07-compact-responses`
- [ ] PRE-3: Carry forward from the S04 retro. M01 is closed. CI, the stubbed
      websocket path and unverified tool descriptions all remain open and are not
      this story

## 5. Implementation steps

### Step 1: Capture the baseline

**Files touched:** none.

**What changes:** Run `tools/compare_wire.py` before anything, and record the
size of every captured response. Size becomes a measured property rather than an
impression.

**How to check it worked:** a baseline file exists with eleven responses and
their character counts.

### Step 2: Stop paying for whitespace

**Files touched:** `server.py`, every `json.dumps`.

**What changes:** compact separators instead of `indent=2`. This is 28% for no
loss of information whatsoever. A model does not need the file to be pretty and
nobody reads it with their eyes.

**How to check it worked:** the same response parses to an identical object and
is 28% shorter.

### Step 3: Stop paying for false precision

**Files touched:** `server.py` or `ais_mapping.py`.

**What changes:** `lat` and `lon` rounded to four decimal places, about 11
metres. AIS position accuracy is nowhere near the sixteen significant figures a
Python float prints, so the extra digits are noise that looks like data.
`speed_knots` and `distance_nm` get the same treatment.

**How to check it worked:** a known vessel's position still resolves to the same
place on a chart, and the payload shrinks.

### Step 4: Stop repeating yourself

**Files touched:** `server.py`.

**What changes:** `position_age_seconds` comes out of each vessel, since the
provenance block already carries the oldest. `nearest_port` comes out when the
caller named a port, because in that case every vessel has the same value and the
caller already knows it.

**How to check it worked:** both fields still appear where they carry
information, `vessel_details` and unfiltered searches, and are absent where they
do not.

### Step 5: Decide about nulls, then act on the decision

**Files touched:** `server.py`, tool descriptions.

**What changes:** depends on the gate. Dropping null fields saves 10%, and it
softens what S02 promised: that an unknown value is explicitly `null` rather than
missing. Absent and null are different claims. Absent can read as "the server did
not send this"; null says "we do not know this".

If taken, the tool descriptions must state that an absent field means AIS has not
reported it, so the honesty moves from the payload into the contract rather than
disappearing.

**How to check it worked:** whichever way it goes, the description and the
behaviour agree.

### Step 6: Bound the response

**Files touched:** `server.py`.

**What changes:** a `limit` parameter, defaulting to something sensible, with the
schema publishing its bounds the way S06 did for `radius_nm`. The response states
how many matched and how many were returned, so a truncated answer announces
itself.

**A cap that silently drops results is worse than a large response.** The
difference between "27 vessels" and "27 of 49 vessels, nearest first" is the
difference between a useful answer and a wrong one.

**How to check it worked:** asking for 5 returns 5 and says 49 matched. Asking
for more than exist returns what exists without complaint.

### Step 7: Update the tests and the documentation

**Files touched:** `tests/`, `README.md`.

**What changes:** tests that assert on key sets or counts are updated
deliberately, and new tests assert measured sizes so a regression is caught.
The README documents the `limit` parameter and, if relevant, the null decision.

**How to check it worked:** the suite passes, and the size assertions are shown
to fail against the pre-change code.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | The headline call returns under 12,000 characters, down from 26,713 | [x] |
| AC-2 | The response parses to the same vessels, in the same order, with the same MMSIs | [x] |
| AC-3 | Coordinates round trip within 15 metres of the original | [x] |
| AC-4 | The provenance block is unchanged | [x] |
| AC-5 | `nearest_port` is absent when the caller named a port, present when they did not | [x] |
| AC-6 | A capped response states both matched and returned | [x] |
| AC-7 | `limit` publishes its bounds in the schema | [x] |
| AC-8 | The null decision and the description agree | [x] |
| AC-9 | No unknown value is made to look known | [x] |
| AC-10 | The wire capture shows the same eleven responses, semantically unchanged | [x] |
| AC-11 | The size assertions are demonstrated to fail against the pre-change code | [x] |
| AC-12 | The full suite passes and every recorded command runs | [x] |

### Evidence

**173 tests, up from 157.** Sixteen new.

- **AC-1.** `vessels_near_port("Tanjung Pelepas", 40)` against the fixture:
  26,713 characters before, **13,606 uncapped (50% smaller)** and **5,087 at the
  default limit of 25 (81% smaller)**. Roughly 6,678 tokens down to 1,271.
- **AC-2.** `test_truncation_keeps_the_nearest_vessels` asserts the capped list
  is the same MMSIs in the same order as the head of the full list.
- **AC-3.** Asserted numerically rather than by eye: every vessel's rounded
  position is within 15 metres of the raw value, using 111 km per degree.
- **AC-4, AC-10.** `tools/compare_wire.py` captured eleven responses before and
  after. Every response carries the same semantic content. The error paths,
  `initialize` and `resources_list` are byte identical.
- **AC-5.** Two tests: absent with `position_age_seconds` when a port was named,
  present on every vessel when it was not.
- **AC-6.** `limit=5` reports `matches: 67, returned: 5`. A larger limit than the
  result set reports both as 67 without complaint.
- **AC-7.** Both tools publish
  `{"default": 25, "exclusiveMinimum": 0, "maximum": 200, "type": "integer"}`.
  Over the wire, 0, -1, 201 and 1000 are all rejected naming `limit`.
- **AC-8, AC-9.** **Nulls were kept.** `test_unknown_values_are_still_null_not_absent`
  asserts the key is present holding null for vessels with no static data. The
  README states it.
- **AC-11.** Three isolated reversions. Removing compact serialisation failed
  two named size tests; removing rounding failed the precision test; removing the
  `returned` field failed two truncation tests. Restored, 173 pass.
- **AC-12.** `pytest` and the smoke test, both verbatim, both pass.

### The cost this story added

`tools/list` grew from 3,344 to 4,301 characters, 29%, because two tools gained a
`limit` parameter with a real description. That is paid once per session against
savings on every call, and pays for itself before the first call completes:

| Calls in a session | Before | After |
|--------------------|--------|-------|
| 1 | 30,057 | 9,388 (68% less) |
| 3 | 83,483 | 19,562 (76% less) |
| 10 | 270,474 | 55,171 (79% less) |

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| none expected | |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/server.py` | serialisation, rounding, redundant fields, `limit` |
| `maritime_mcp_server/ais_mapping.py` | rounding, if it belongs there rather than at the edge |
| `tests/test_server.py` | updated assertions, new size assertions |
| `README.md` | the `limit` parameter and the response shape |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Dropping nulls weakens S02's promise** that unknown means explicitly null | certain if taken | an absent field is a different claim from a null one, and the difference is exactly the honesty this project has been careful about | Gate decision, not a build decision. If taken, the contract moves into the tool description rather than vanishing |
| A cap silently truncates and the caller believes they saw everything | medium | a wrong answer that looks complete, which is the failure mode S06 was about | AC-6 requires the response to state matched and returned separately |
| Optimising for size makes answers thinner rather than tighter | medium | the tool becomes less useful while looking more efficient | Every reduction must be justified as redundancy or false precision. AC-2 and AC-9 are the checks |
| All measurements come from one 89 vessel fixture | certain | a live store behaves differently and the percentages will shift | Stated per G15. The fixture is what can be measured repeatably; live figures will be sampled once and labelled as such |
| Rounding coordinates loses something that matters | low | a vessel appears slightly displaced | Four decimals is about 11 metres. AIS position reports are not that accurate, and AC-3 bounds the error |
| Tests assert on the old shape and get "updated" into meaninglessness | medium | a green suite that no longer checks anything | Each changed assertion must be justified in the diff, and AC-11 requires the new size assertions to be proven able to fail |

## 9. Out of scope

- **Splitting the collector from the server lifecycle.** The larger design fix,
  and the right subject for its own milestone.
- **Persisting state so the fallback is last known data.** Depends on the above.
- **Continuous integration.** Still the most valuable unstarted infrastructure
  work, and unrelated to response size.
- **Changing which vessels are returned.** This story changes how an answer is
  written, and caps how much of it comes back at once. It does not change what
  counts as a match.
- **A separate summary tool.** Considered, and left out deliberately: the
  measured wins above get 60% without adding surface area, and a `limit` gets the
  rest. Adding a fourth tool should wait until there is evidence the three are
  not enough.

## 10. Verification

```
# baseline, before anything changes
python tools/compare_wire.py --out before.json

# after
python tools/compare_wire.py --out after.json

# sizes side by side, and the semantic diff
# expect large size reductions and no change to which vessels appear

# the suite
.venv/bin/python -m pytest
.venv/bin/python -m maritime_mcp_server.smoke_test

# AC-11, proving the size assertions can fail
# revert the serialisation change, run the size tests, expect failure, restore
```

**Result:** run on 2026-09-15. All twelve criteria met, measured against the
committed fixture rather than estimated.
