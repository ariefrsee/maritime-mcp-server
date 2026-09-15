# S07 Test Script: Compact responses

**Story:** S07 | **Branch:** `feat/S07-compact-responses` | **Date:** 2026-09-15

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails.

**Run by the assistant on 2026-09-15, at the user's instruction**, as in every
story. These results were produced and read by the same party that wrote the code.

This story is about size, so most cases are measurements rather than checks that
something works. A measurement without a before is not evidence, so every size
case compares against a capture taken before any code changed.

No API key or network needed.

---

## Prerequisites

- [x] On branch `feat/S07-compact-responses`
- [x] A wire capture was taken **before** any change
- [x] `pip install -e ".[dev]"` has been run

---

## Test cases

### TC1: The headline question got much smaller

**Covers:** AC-1

**Purpose:** The whole story in one number.

**Steps:**
1. Call `vessels_near_port("Tanjung Pelepas", 40)` against the committed fixture,
   uncapped and at the default limit.
2. Compare against the 26,713 characters recorded before the change.

**Expected:** a large reduction, with the same vessels.

**Result:** [x] Pass

**Notes:**

```
before                       26,713 chars  ~6,678 tok
after, uncapped (67 vessels) 13,606 chars  ~3,401 tok   50% smaller
after, default limit of 25    5,087 chars  ~1,271 tok   81% smaller
```

The uncapped figure is the honest one for comparing like with like: it is the
same 67 vessels, written down differently.

---

### TC2: It is the same answer, not a smaller one

**Covers:** AC-2, AC-9

**Purpose:** The obvious way to make a response smaller is to say less. That
would be a worse tool wearing a better number.

**Steps:**
1. Compare the capped list against the head of the full list, by MMSI and order.
2. Check that vessels with no static data still carry `type` as an explicit null.

**Expected:** identical MMSIs in identical order, and nulls still present.

**Result:** [x] Pass

**Notes:** Truncation keeps the nearest, not an arbitrary subset. Nulls were
deliberately kept, see TC6.

---

### TC3: Nothing is pretty-printed any more

**Covers:** AC-1

**Purpose:** 29% of the original payload was indentation. Nobody reads this with
their eyes.

**Steps:**
1. Assert no newline appears in a response.

**Expected:** compact separators throughout, including the error paths.

**Result:** [x] Pass

**Notes:** This single change was worth 28% on its own, for no loss of
information at all.

---

### TC4: Coordinates lost digits, not accuracy

**Covers:** AC-3

**Purpose:** Rounding is only acceptable if the error is below the source's own
accuracy. Otherwise it is data loss dressed as efficiency.

**Steps:**
1. Assert every returned coordinate has at most four decimal places.
2. Assert each rounded position is within 15 metres of the raw value, using
   111 km per degree of latitude.

**Expected:** both hold for every vessel in the fixture.

**Result:** [x] Pass

**Notes:** Four decimals is about 11 metres. A position like
`1.2196916666666666` was printing sixteen significant figures for a measurement
that is not accurate to one.

---

### TC5: A capped answer says it is capped

**Covers:** AC-6, AC-7

**Purpose:** The failure this case exists to prevent is the one S06 was about: a
confident answer that is quietly incomplete.

**Steps:**
1. Call with `limit=5` and read `matches` and `returned`.
2. Call with a limit larger than the result set.
3. Over the wire, try limits of 0, -1, 201 and 1000.

**Expected:** `matches: 67, returned: 5`. A large limit returns everything
without complaint. Out of range limits are rejected naming `limit`.

**Result:** [x] Pass

**Notes:** The bounds are published in the schema as
`{"default": 25, "exclusiveMinimum": 0, "maximum": 200}`, so a client sees them
before calling, the same pattern S06 established.

---

### TC6: Unknown is still unknown, not missing

**Covers:** AC-8, AC-9

**Purpose:** Dropping null fields would have saved a further 10%. It was
declined, and this case records that decision as a property of the code rather
than a note in a plan.

**Steps:**
1. Find a vessel in the fixture with no static data.
2. Assert the `type` key is present and holds null.
3. Read the README and confirm it says the same thing.

**Expected:** key present, value null, documentation agrees.

**Result:** [x] Pass

**Notes:** Absent and null are different claims. Absent reads as "the server did
not send this"; null says "we do not know this". S02 established that
distinction and this story keeps it, at a measured cost of about 10%.

---

### TC7: Redundant fields are gone, and only where they are redundant

**Covers:** AC-5

**Purpose:** `nearest_port` was 8% of the payload, repeating the port you just
asked about, 67 times.

**Steps:**
1. Call `vessels_near_port` and assert `nearest_port` and `position_age_seconds`
   are absent from each vessel.
2. Call `search_vessels` and assert `nearest_port` is present.

**Expected:** absent where the caller already knows, present where they do not.

**Result:** [x] Pass

**Notes:** `position_age_seconds` was 7%, duplicating per vessel what the
provenance block already summarises as `oldest_position_age_seconds`.

---

### TC8: Nothing else about the responses moved

**Covers:** AC-4, AC-10

**Steps:**
1. `python tools/compare_wire.py --out before.json` before any change.
2. The same after.
3. Compare content, not size.

**Expected:** the same eleven responses, semantically identical. The error paths,
`initialize` and `resources_list` byte identical.

**Result:** [x] Pass

**Notes:** The provenance block is untouched: source, count, and either the
snapshot date or the oldest age.

---

### TC9: The size assertions can fail

**Covers:** AC-11

**Purpose:** Per G17. Sixteen tests were added and all passed first time, which
proves nothing on its own.

**Steps:**
1. Revert only the compact serialisation. Run the size tests.
2. Restore. Revert only the rounding. Run the precision tests.
3. Restore. Revert only the `returned` field. Run the truncation tests.
4. Restore and run everything.

**Expected:** two named failures, then one, then two, then 173 passing.

**Result:** [x] Pass

**Notes:** One honest detail.
`test_rounding_moves_a_vessel_by_less_than_fifteen_metres` **passed** with
rounding removed, correctly: it bounds the error, and no rounding means no error.
`test_coordinates_are_rounded_to_about_eleven_metres` is the one that detects the
feature. Worth knowing which test does which job.

---

### TC10: The tool schema got bigger, and that is still a win

**Covers:** an honest accounting

**Purpose:** Adding a `limit` parameter with a real description is not free.

**Steps:**
1. Compare the size of `tools/list` before and after.
2. Work out the break even point.

**Expected:** a larger schema, repaid quickly.

**Result:** [x] Pass

**Notes:** `tools/list` grew from 3,344 to 4,301 characters, 29%, paid once per
session. Against per call savings:

```
 1 call :  30,057 ->  9,388   68% less
 3 calls:  83,483 -> 19,562   76% less
10 calls: 270,474 -> 55,171   79% less
```

It pays for itself before the first call completes.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC1, TC3 | [x] |
| AC-2 | TC2 | [x] |
| AC-3 | TC4 | [x] |
| AC-4 | TC8 | [x] |
| AC-5 | TC7 | [x] |
| AC-6 | TC5 | [x] |
| AC-7 | TC5 | [x] |
| AC-8 | TC6 | [x] |
| AC-9 | TC2, TC6 | [x] |
| AC-10 | TC8 | [x] |
| AC-11 | TC9 | [x] |
| AC-12 | TC1 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**No case failed.** Two things worth recording rather than failures:

1. **The tool schema grew.** Measured and accounted for in TC10 rather than
   quietly ignored because the headline number looked good.
2. **One new test does not detect the feature it appears to guard.** Named in
   TC9. It bounds an error rather than asserting a behaviour, which is a
   legitimate job, but not the one its name suggests at a glance.

**What this script does not tell you.** Every number here comes from one 89
vessel fixture. A busy live store has more vessels with more static data filled
in, so both the absolute sizes and the percentages will differ. The default limit
of 25 also becomes more significant as traffic grows, which is the point, but its
effect on answer quality has never been observed in a real conversation.
