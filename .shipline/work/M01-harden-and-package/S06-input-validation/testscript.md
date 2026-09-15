# S06 Test Script: Validate tool inputs

**Story:** S06 | **Branch:** `feat/S06-input-validation` | **Date:** 2026-09-15

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails.

**Run by the assistant on 2026-09-15, at the user's instruction**, as in every
story. These results were produced and read by the same party that wrote the code.

Every case here goes **over the wire**, through `tools/call`, not by calling
Python functions. That is not stylistic: the bounds are enforced by the protocol
layer, and a direct call bypasses them entirely. A test calling the function
directly would pass against both the old and the new code.

No API key or network needed.

---

## Prerequisites

- [x] On branch `feat/S06-input-validation`
- [x] `pip install -e ".[dev]"` has been run
- [x] The server starts with no key, in snapshot mode

---

## Test cases

### TC1: A meaningless radius is refused

**Covers:** AC-1, AC-2

**Purpose:** Returning an empty list for a negative radius is a claim about the
sea, not about the question.

**Steps:**
1. Call `vessels_near_port` with `radius_nm` of `-5`, `0`, `1000` and `501`.
2. Call it with `30`, `0.1` and `500`.

**Expected:** the first four rejected with a validation error naming `radius_nm`.
The last three accepted, with `30` returning 5 vessels near Port Klang.

**Result:** [x] Pass

**Notes:** Before this story all four invalid values returned `ok` with 0 or 18
matches and no complaint.

---

### TC2: The client can see the bounds without calling

**Covers:** AC-3

**Purpose:** A rejection after the fact is worse than a schema the AI reads
first. This is the part that prevents bad calls rather than punishing them.

**Steps:**
1. Send `tools/list` and read `inputSchema.properties.radius_nm`.

**Expected:** `exclusiveMinimum: 0`, `maximum: 500`, and a description that
explains the ceiling.

**Result:** [x] Pass

**Notes:**
```json
{"default": 30.0, "exclusiveMinimum": 0, "maximum": 500, "type": "number",
 "description": "Search radius in nautical miles, greater than 0 and at most 500..."}
```

---

### TC3: Asking for nothing gets a useful answer

**Covers:** AC-4

**Purpose:** Being told your empty query matched 18 vessels and you should be
more specific is nonsense. You did not ask for anything.

**Steps:**
1. Call `vessel_details` with `""`, `"   "`, a tab and a newline.
2. Call it with `"Kowloon"`.

**Expected:** the four blanks return an error asking for a name or MMSI, still
carrying the provenance block and with no `candidates` list. `"Kowloon"`
resolves to Kowloon Express.

**Result:** [x] Pass

**Notes:** `"A vessel name or MMSI is required. Pass part of a ship's name, or
its nine digit MMSI."`

---

### TC4: A stray space no longer produces a wrong answer

**Covers:** AC-5

**Purpose:** **The most important case here.** This was not a crash. It was a
confident, plausible, wrong answer that an AI assistant would have relayed as
fact.

**Steps:**
1. Call `search_vessels` with `flag=" malaysia "`.
2. Call it with `flag="malaysia"`.
3. Compare both the count and the MMSIs returned.

**Expected:** both return 7 vessels, in the same order.

**Result:** [x] Pass

**Notes:** Before this story: `" malaysia "` returned 0 and `"malaysia"` returned
7. The asymmetry existed because `vessels_near_port` already stripped its port
while the search filters did not.

---

### TC5: A blank filter means no filter

**Covers:** AC-6

**Purpose:** A deliberate decision, recorded so it is not mistaken for an
accident. The alternative, matching nothing, is the behaviour this story removed
elsewhere.

**Steps:**
1. Call `search_vessels` with `flag="   "`.
2. Call it with `vessel_type="  "` and `status="  "`.

**Expected:** both return all 18, the same as passing nothing.

**Result:** [x] Pass

---

### TC6: Every parameter tells the client what it wants

**Covers:** AC-7

**Purpose:** The AI reads these to decide how to call a tool. A missing
description makes a bad call more likely, not merely less documented.

**Steps:**
1. Send `tools/list` and enumerate every property of every tool's `inputSchema`.
2. Assert each has a non-empty description.

**Expected:** six parameters across three tools, none missing.

**Result:** [x] Pass

**Notes:** Enumerated by script rather than read, per G18.

---

### TC7: The new tests can actually fail

**Covers:** AC-8

**Purpose:** Per G17. Seven tests were added and all passed on first run, which
on its own is evidence of nothing.

**Steps:**
1. Revert only the filter normalisation. Run the filter tests.
2. Restore. Revert only the blank query check. Run the query tests.
3. Restore and run everything.

**Expected:** three named failures, then four, then 157 passing.

**Result:** [x] Pass

**Notes:** Each reversion isolated one change, so each failure points at one
cause rather than a general breakage.

---

### TC8: Nothing that worked before behaves differently

**Covers:** AC-9, AC-10

**Steps:**
1. `pytest`
2. `python -m maritime_mcp_server.smoke_test`

**Expected:** 157 passed. The 140 pre-existing tests unchanged, except the one
S05 wrote specifically to be replaced here. The smoke test unaffected.

**Result:** [x] Pass

---

### TC9: Direct Python calls still bypass validation

**Covers:** a limitation, not a criterion

**Purpose:** Honesty about where the validation actually lives.

**Steps:**
1. Call `vessels_near_port("Port Klang", radius_nm=-5)` directly in Python.

**Expected:** 0 matches, no error. The constraint is enforced by the protocol
layer and a direct call skips it.

**Result:** [x] Pass, in the sense that it behaves as documented

**Notes:** No client calls these functions directly, but the smoke test does, so
the smoke test gets no input validation. There is a test recording this
explicitly. Duplicating the bounds inside the function would create two places to
keep in step, which is why it was not done.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC1 | [x] |
| AC-2 | TC1 | [x] |
| AC-3 | TC2 | [x] |
| AC-4 | TC3 | [x] |
| AC-5 | TC4 | [x] |
| AC-6 | TC5 | [x] |
| AC-7 | TC6 | [x] |
| AC-8 | TC7 | [x] |
| AC-9 | TC8 | [x] |
| AC-10 | TC8 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Found during the story, both recorded as divergences:**

1. **The plan asserted five Malaysian vessels and there are seven.** Caught by
   the very first command run on the branch. Third time G2 has caught a number
   written from memory, and the first time inside a story about misleading
   answers. Divergence D-1.
2. **Validation lives at the protocol boundary, not in the function.** Discovered
   while deciding how to write the test. The criteria were phrased "over the
   wire", which turned out to be load bearing. Divergence D-2.

**What these cases do not cover.** Whether the descriptions are *accurate*, only
that they exist. If the radius ceiling changes and the description does not, no
test here notices.
