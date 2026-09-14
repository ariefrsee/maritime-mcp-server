# S05 Test Script: A real test suite

**Story:** S05 | **Branch:** `feat/S05-test-suite` | **Date:** 2026-09-14

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails. Do not tick a case you did not actually run.

**Run by the assistant on 2026-09-14, at the user's instruction**, as in every
story so far. Recorded plainly: these results were produced and read by the same
party that wrote the code.

There is an obvious circularity in a test script for a test suite. These cases
deliberately do **not** re-run the suite and call it proof. They check the things
a passing suite cannot tell you: that it can fail, that it covers what it claims,
that it does not reach the network, and that it does not ship to users.

Nothing here needs an API key or a network connection.

```bash
cd /Users/ariefrse/maritime-mcp-server
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Prerequisites

- [x] On branch `feat/S05-test-suite`
- [x] Python 3.11 or newer. Tested on 3.14.6
- [x] `pip install -e ".[dev]"` has been run

---

## Test cases

### TC1: The suite runs and passes

**Covers:** AC-3, AC-11

**Steps:**
1. `pytest`
2. `python -m maritime_mcp_server.smoke_test`

**Expected:** 140 passed, in well under a second. The smoke test ends with
`All smoke checks passed.`

**Result:** [x] Pass

**Notes:** 140 tests in 0.51s. 72 mapping, 24 store, 21 collector, 23 server.
Counts read from the run output rather than estimated.

---

### TC2: The suite can actually fail

**Covers:** AC-4

**Purpose:** **The most important case here.** A suite that has never failed is
not evidence of anything. This reintroduces the exact bug that passed seven
acceptance criteria and eight test cases in S03.

**Steps:**
1. In `maritime_mcp_server/collector.py`, delete the `failures = 0` line inside
   the `if await self._session():` branch.
2. `pytest tests/test_collector.py`
3. Restore the line and re-run.

**Expected:** named failures, not a vague one. Then green again.

**Result:** [x] Pass

**Notes:** Two tests failed, `test_a_productive_session_resets_the_failure_count`
and `test_alternating_success_and_failure_never_gives_up`, with the captured log
showing `Giving up on live AIS after 4 consecutive failures`. Restoring the line
returned all 21 to passing.

---

### TC3: Coverage of the mapping layer is real, not assumed

**Covers:** AC-5

**Purpose:** A green suite says nothing about what it left out.

**Steps:**
1. Run a script that lists every public function in `ais_mapping` and greps the
   test file for a direct reference to each.

**Expected:** eleven functions, none untested.

**Result:** [x] Pass

**Notes:** **Failed on the first attempt.** `position_fields` and `static_fields`
were exercised only through `to_record`. Four direct tests were added rather than
the criterion being relaxed. Divergence D-2.

---

### TC4: Nothing reaches the network

**Covers:** AC-10

**Purpose:** A suite that quietly depends on the internet fails for the wrong
reasons and stops being trusted.

**Steps:**
1. Run the suite with `socket.socket.connect`, `socket.create_connection`,
   `socket.socket.connect_ex` and `socket.getaddrinfo` all replaced by functions
   that raise, and `AISSTREAM_API_KEY` unset.

**Expected:** all 140 pass.

**Result:** [x] Pass

**Notes:** No test opened a socket or looked up a hostname.

---

### TC5: Nothing depends on the wall clock

**Covers:** AC-10

**Purpose:** The store expires entries by time. A test that reads the real clock
works today and fails next year.

**Steps:**
1. Patch `datetime.datetime.now` to return 2027-09-14 and run the suite.

**Expected:** all 140 pass, because every time sensitive test injects its own
`now`.

**Result:** [x] Pass

**Notes:** Identical result a year in the future.

---

### TC6: The suite runs from anywhere

**Covers:** AC-3

**Steps:**
1. `cd /tmp`
2. Run pytest against the absolute path of the tests directory.

**Expected:** all 140 pass.

**Result:** [x] Pass

**Notes:** **Found a real fragility first.** The suite originally imported shared
builders via `from tests.conftest import ...`, which needs the repository root on
`sys.path`. It worked under `python -m pytest` and failed every other way,
including from CI. Builders moved to `tests/helpers.py`. Divergence D-1.

---

### TC7: Tests do not ship to users

**Covers:** AC-1, AC-2

**Purpose:** S01 established that packaging assumptions are where this project
goes wrong.

**Steps:**
1. `python -m build --wheel`
2. List the wheel contents and grep for `tests`.
3. Read `Requires-Dist` and `Provides-Extra` from the wheel metadata.
4. Install the wheel plainly into a venv outside the repository and try
   `import pytest`.

**Expected:** no `tests/` entries, `Provides-Extra: dev`, `pytest` only under the
extra, and `import pytest` failing after a plain install.

**Result:** [x] Pass

**Notes:** Zero `tests/` entries. The wheel ships six modules. `import pytest`
fails in the plain environment while the server imports fine.

---

### TC8: The secret hygiene test is honest

**Covers:** AC-7

**Purpose:** A test asserting "the key is not in the log" is worthless if the
code path never puts it there in the first place.

**Steps:**
1. Read `test_the_api_key_never_reaches_a_log_record` and confirm the exception
   it raises genuinely embeds the key in its message.
2. Temporarily change the collector to log `%s` of the exception instead of its
   type, and confirm the test fails.

**Expected:** the test fails when the code is made careless.

**Result:** [x] Pass

**Notes:** Mutation actually performed, not reasoned about. Changing
`type(exc).__name__` to `exc` in the warning made the test fail immediately, with
the captured log showing the key in four separate lines:

```
WARNING AIS connection failed (handshake failed for wss://stream?apikey=test-key-not-a-real-one), retry 1 in 0s
```

Restoring the line returned it to passing. The test also asserts that
`ConnectionError` **is** present, so it cannot pass by logging nothing at all.

---

### TC9: The tests assert values, not shapes

**Covers:** AC-6, AC-8, AC-9, and G11 generally

**Purpose:** The guardrail this story was built around.

**Steps:**
1. Read the assertions in `test_ais_mapping.py` and confirm they name expected
   values rather than checking types or truthiness.
2. Confirm `flag_from_mmsi("995331385")` is asserted as Malaysia.
3. Confirm both merge orders are covered.
4. Confirm `nearest_port` is asserted as `Port Klang` and `Tanjung Pelepas` for
   vessels at stated coordinates.

**Expected:** all four present.

**Result:** [x] Pass

**Notes:** The fixture vessel count is pinned to 89 exactly rather than
"non-zero", so a mapping regression changes it and fails.

---

### TC10: Current wrong behaviour is recorded as wrong

**Covers:** scope honesty

**Purpose:** Input validation is milestone goal G3 and out of scope here. The
risk is that writing tests now quietly blesses behaviour that should change.

**Steps:**
1. Read `test_a_negative_radius_currently_returns_nothing`.

**Expected:** the test records current behaviour and its docstring says plainly
that it is not an endorsement, so that when validation lands the test must be
updated deliberately.

**Result:** [x] Pass

**Notes:** `vessels_near_port("Port Klang", radius_nm=-5)` returns an empty list
with no error. That is wrong and is now written down as wrong.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC7 | [x] |
| AC-2 | TC7 | [x] |
| AC-3 | TC1, TC6 | [x] |
| AC-4 | TC2 | [x] |
| AC-5 | TC3 | [x] |
| AC-6 | TC9 | [x] |
| AC-7 | TC8 | [x] |
| AC-8 | TC9 | [x] |
| AC-9 | TC9 | [x] |
| AC-10 | TC4, TC5 | [x] |
| AC-11 | TC1 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Failures found during the run, all fixed:**

1. **TC6 found a real fragility.** `from tests.conftest import ...` only worked
   when invoked as `python -m pytest` from the repository root. Fixed by moving
   the builders to `tests/helpers.py`. Divergence D-1.
2. **TC3 failed on first attempt.** Two public functions were covered only
   indirectly. Four direct tests added, criterion not relaxed. Divergence D-2.
3. **A test asserted the wrong country.** MMSI 314 is Barbados, not the Bahamas.
   The code was right and the test was wrong. Divergence D-3.

That third one is the first time in this project a mistake was caught by a
machine rather than by a person reading output. It is a small mistake and it is
the entire justification for the story.

**What this script does not tell you.** The suite covers what the retros said
mattered. It does not prove the codebase is correct, only that the specific
behaviours named in sixteen guardrails and five retros still hold. There is no
coverage measurement, deliberately, and no test of the real websocket path.
