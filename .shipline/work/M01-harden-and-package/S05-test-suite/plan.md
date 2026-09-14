---
pipeline_state:
  story_id: S05
  milestone: M01
  title: A real test suite
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S05-test-suite
  started_at: 2026-09-14
  last_updated: 2026-09-14
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14, G15, G16]
---

# S05: A real test suite

## 1. What this is

Nothing a user can see changes. What changes is that the project stops depending
on a person running a script and reading the output carefully.

Right now every behaviour in this codebase is verified by one of three things: a
smoke test with six assertions, a replay script that prints tables for a human to
read, or a throwaway snippet written during a story and then deleted. Three
stories have shipped that way. Today that produced a bug which passed seven
acceptance criteria and eight test cases, and was found by reading code.

After this story, running one command checks every behaviour the guardrails say
matters, and says plainly which ones broke.

## 2. Maturity assessment

Nothing exists. But the code was written with testing in mind even though no
tests were written, which makes this cheaper than it looks.

### Dependencies

| Dependency | Status | What it provides |
|------------|--------|------------------|
| `pytest` | **not installed, not declared.** Latest is 9.1.1, `requires-python >=3.10`, comfortably inside this project's 3.11 floor | the runner and assertion rewriting |
| `anyio` | **already installed at 4.15.1**, as a transitive dependency of `mcp`, alongside `httpx`, `starlette` and `sse-starlette` | its pytest plugin, for testing the collector's async retry loop. No new runtime dependency |
| Captured AIS fixture | already committed at `tests/data/ais_capture.json`, 145 KB, 199 real messages | real input rather than invented input |

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| `tests/` directory | exists, holds only `data/` | `tests/` |
| Real message fixture | 199 messages, all four observed types | `tests/data/ais_capture.json` |
| Injectable clock | `records(now=...)` and `prune(now=...)` already take a time, so eviction is testable without sleeping | `store.py` |
| Network separated from parsing | `Collector.handle()` takes a raw frame and never touches the socket | `collector.py` |
| Pure mapping layer | `ais_mapping` has no state and no IO at all | `ais_mapping.py` |
| Source seam | `set_store()` lets a test swap the data source | `server.py` |
| Smoke test, 6 assertions | stays as the fast offline check and the documented one | `smoke_test.py` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| `pytest` declared as a dev dependency with a ceiling | low | low |
| Tests for the mapping layer, 11 public functions | low | low, it is pure |
| Tests for the store: merge, eviction, rejection, non-ship filtering | medium | low, the clock is injectable |
| Tests for the collector's retry policy, including the mixed case | **medium to high** | the only async code, and the place the real bug lived |
| Tests for the server's seam, provenance and tool output | medium | medium, tools return JSON strings so tests must parse |

**Maturity rating: 5/10.** No test exists, which would normally mean 1 or 2. It is
higher because every seam a test needs is already there: an injectable clock, a
parse step split from the socket, a swappable data source and a committed fixture
of real input. That was luck as much as design, but it is the situation.

## 3. Guardrails that apply

All sixteen are active. Nine bear on this story directly, and two of them are the
reason it exists.

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G1 | Every dependency gets an upper bound at the next major version | `pytest` must be declared `>=9,<10`, not left open, even though it is only a dev dependency |
| G2 | Never write a checkable fact into a plan without running the command that checks it | The version numbers, the Python floors and the fact that `anyio` is already present all came from querying PyPI and the installed environment while writing this |
| G4 | Verify packaging with a built artifact installed outside the repository | Tests must **not** ship in the wheel. This story adds a `tests/` package and it would be easy to start shipping it by accident |
| G5 | A criterion must be evaluable at the phase that checks it | Every criterion below runs during build with no key and no network |
| G6 | Read the staged file list before every commit | A test fixture capturing a live session could contain a key. The existing fixture was checked; any new one must be too |
| G8 | Never present data in a field the source did not supply | The tests must assert this, not just the code. Unknown codes report themselves, absent fields stay null |
| G11 | A criterion that checks shape must not stand in for one that checks behaviour | **The rule this story is built around.** Every test asserts a value. A test that only checks a key exists, a call returns, or a count is non-zero does not count as coverage |
| G15 | Say when a criterion was verified once against conditions that vary | Tests must not depend on live traffic, the time of day, or the network. Anything that would, does not belong here |
| G16 | Test the mixed case, not only total success and total failure | **The other rule this story is built around.** The collector tests must cover works, then fails, then works again. That is the shape the real bug lived in |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected
- [ ] PRE-2: Cut `feat/S05-test-suite`
- [ ] PRE-3: Carry forward from the S03 retro. This story closes the "milestone
      goal G2 is three stories overdue" item. The bounding box being hardcoded,
      S04 needing a re-read, and `tools/compare_wire.py` being unwritten all stay
      open and out of scope

## 5. Implementation steps

### Step 1: Add pytest without letting tests into the wheel

**Files touched:** `pyproject.toml`, new `tests/__init__.py` deliberately absent.

**What changes:** A `[project.optional-dependencies]` block with
`dev = ["pytest>=9,<10"]`, so `pip install -e ".[dev]"` gets the runner and a
plain install does not. `[tool.setuptools] packages` already names
`maritime_mcp_server` explicitly, so `tests/` is not picked up, but that must be
confirmed rather than assumed, because S01's retro established that packaging
assumptions are where this project goes wrong.

Add a `[tool.pytest.ini_options]` block setting `testpaths = ["tests"]` so a bare
`pytest` does the right thing.

**How to check it worked:** `pip install -e ".[dev]"` brings in pytest. A built
wheel contains no `tests/` entries. A plain `pip install .` into a clean
environment does not install pytest.

### Step 2: Test the mapping layer

**Files touched:** new `tests/test_ais_mapping.py`.

**What changes:** Tests for all eleven public functions, asserting values.

The cases that matter, each traceable to something a retro found:

- Every navigational status 0 to 15 maps to a distinct non-empty string, and an
  unknown code returns `Unknown status 99` rather than a guess.
- `None` status returns `None`, because Class B transponders do not send one and
  defaulting it to "Under way" would be a fabrication.
- Ship types map by decade, with the specific overrides checked individually.
- `mmsi_kind` classifies all seven station types, using the real examples found
  in live traffic: `995331385` is an aid to navigation, `9135649` is malformed.
- `flag_from_mmsi` takes the country digits from the **right offset per station
  type**, which is the bug S02 found: `995331385` is Malaysia, from digits in the
  middle, not `995` from the front.
- `length_from_dimension` returns `None` for a zero total, not `0`.
- `parse_time` handles the real Go format with nanoseconds and a trailing zone
  name, and returns `None` rather than raising on rubbish.

**How to check it worked:** the tests pass, and each assertion names an expected
value rather than a type or a truthiness.

### Step 3: Test the store

**Files touched:** new `tests/test_store.py`.

**What changes:** Uses the injectable clock, so nothing sleeps.

- A position, then a later `ShipStaticData` for the same MMSI, produces **one**
  record carrying both halves.
- Static data arriving **first**, then a position, also merges. The S02 tests only
  ever covered one order.
- Eviction: present before `max_age`, gone after.
- `Valid: false`, `SubscriptionConfirmation`, malformed JSON, `None` and an
  integer are all rejected without raising.
- Non-ship stations are excluded from `records()` but counted in `counts()`.
- `require_position=False` returns a vessel that has identity but no position,
  with `position_age_seconds` as `None` rather than a fabricated number.
- The whole committed fixture replays to a stable, asserted vessel count.

**How to check it worked:** the tests pass and the fixture count is pinned to an
exact number, so a mapping regression changes it and fails.

### Step 4: Test the collector, including the mixed case

**Files touched:** new `tests/test_collector.py`.

**What changes:** No network. `_session` is replaced with a stub whose outcome
sequence each test controls.

- **The G16 case:** fails, fails, fails, succeeds, then fails forever. With a cap
  of 4, the collector must attempt 8 sessions. Without the reset it stops at 4.
  This is the test that would have caught the real bug.
- A clean close that delivered nothing counts as a failure, per G14.
- A productive session resets the backoff delay as well as the counter.
- With no key, `start()` returns `False` and creates no task.
- `handle()` never raises on anything, and increments `messages_seen` even for
  frames it rejects.
- **G13:** a session raising an exception whose message contains the key must
  produce a log record that does not. Asserted by capturing log output and
  searching it for the key.

**How to check it worked:** the tests pass, and the G16 test fails if the reset
line is removed. That must be demonstrated, not assumed.

### Step 5: Test the server's seam and output

**Files touched:** new `tests/test_server.py`.

**What changes:**

- With no store, every tool and the resource return `source: snapshot`, the
  correct count and the snapshot date.
- With a store filled from the fixture, they return `source: live`.
- With a store whose entries have expired, they fall back to snapshot.
- `nearest_port` is populated for live records, which is the field S02 promised
  and never implemented. Asserted by value against known coordinates.
- `vessels_near_port` excludes vessels with no position; `vessel_details` includes
  them.
- Filters match case-insensitively and tolerate `None` fields, which is where the
  original code would have raised after the shape change.
- The error paths return an error object **and** a provenance block.

**How to check it worked:** the tests pass and assert values, not key presence.

### Step 6: Make the suite the recorded verify command

**Files touched:** `.shipline/config.json`, `README.md`.

**What changes:** `verify.commands` becomes both the test suite and the smoke
test. The smoke test stays because it is what the README tells a user to run and
it needs no dev install. Document how to run the tests.

**How to check it worked:** every command in `verify.commands` runs as written
and passes.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | `pip install -e ".[dev]"` installs pytest; a plain `pip install .` into a clean environment does not | [x] |
| AC-2 | A built wheel contains no `tests/` entries | [x] |
| AC-3 | `pytest` passes from a clean checkout with no API key and no network access | [x] |
| AC-4 | Deleting the `failures = 0` reset line makes a named test fail. Demonstrated, not asserted | [x] |
| AC-5 | Every one of the eleven public functions in `ais_mapping` has at least one test asserting a specific expected value | [x] |
| AC-6 | `flag_from_mmsi("995331385")` asserted to be Malaysia | [x] |
| AC-7 | A test asserts a log record produced while handling an exception carrying the API key does not contain the key | [x] |
| AC-8 | Tests cover both merge orders | [x] |
| AC-9 | A test asserts `nearest_port` by value for a live record with known coordinates | [x] |
| AC-10 | No test reads the network, requires a key, or depends on the current time other than through an injected clock | [x] |
| AC-11 | Every command in `verify.commands` runs as written and passes | [x] |

### Evidence

**140 tests, 0.5 seconds.** 72 mapping, 24 store, 21 collector, 23 server.

- **AC-1.** Wheel metadata carries `Provides-Extra: dev` and
  `Requires-Dist: pytest<10,>=9; extra == "dev"`. Installed plainly into a venv
  outside the repository, `import pytest` fails while the server imports fine.
- **AC-2.** `tests/ entries in wheel: 0`. The wheel ships six modules and nothing
  else.
- **AC-3 and AC-10.** Run three ways, all 140 passing: with every socket function
  replaced by one that raises and `AISSTREAM_API_KEY` unset; with
  `datetime.datetime.now` patched to 2027; and from `/tmp` with an absolute path.
  Network, clock and working directory independence, demonstrated rather than
  claimed.
- **AC-4.** The `failures = 0` line was deleted and the suite re-run. **Two named
  tests failed**, `test_a_productive_session_resets_the_failure_count` and
  `test_alternating_success_and_failure_never_gives_up`, with the captured log
  showing `Giving up on live AIS after 4 consecutive failures`. The line was
  restored and the suite went green. This is the bug that passed seven acceptance
  criteria in S03.
- **AC-5.** Checked programmatically rather than by eye: all eleven public
  functions are referenced in at least one assertion. The first run of that check
  **failed**, showing `position_fields` and `static_fields` covered only
  indirectly through `to_record`. Direct tests were added rather than the
  criterion relaxed.
- **AC-6.** `test_aid_to_navigation_takes_country_digits_from_the_middle` asserts
  Malaysia for `995331385` and `aid to navigation` for its kind.
- **AC-7.** `test_the_api_key_never_reaches_a_log_record` raises a
  `ConnectionError` whose message embeds the key, captures the log, and asserts
  the key is absent while `ConnectionError` is present.
- **AC-8.** Both orders covered:
  `test_position_then_static_merges_into_one_record` and
  `test_static_then_position_also_merges`. S02 only ever tested one.
- **AC-9.** `test_nearest_port_is_computed_for_live_records` asserts `Port Klang`
  for a vessel at 3.01N 101.37E, and a second test asserts `Tanjung Pelepas` for
  one at 1.30N 103.60E.
- **AC-11.** `.venv/bin/python -m pytest` then
  `.venv/bin/python -m maritime_mcp_server.smoke_test`, both run verbatim, both
  pass.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `tests/test_ais_mapping.py` | the pure layer, eleven functions |
| `tests/test_store.py` | merge, eviction, rejection, filtering |
| `tests/test_collector.py` | retry policy including the mixed case, and secret hygiene |
| `tests/test_server.py` | source seam, provenance, tool output |
| `tests/conftest.py` | shared fixtures: the captured messages, a filled store, an anyio backend |

### Modified

| Path | Change |
|------|--------|
| `pyproject.toml` | `dev` extra with `pytest>=9,<10`, and a pytest config block |
| `.shipline/config.json` | `verify.commands` gains the test suite |
| `README.md` | how to run the tests |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tests get written to match what the code currently does rather than what it should do, locking in a bug | **high, and this is the real risk of writing tests after the fact** | a green suite that proves nothing | Every test traces to a named guardrail or a documented retro finding, not to a reading of the implementation. AC-4 forces one test to be proven capable of failing |
| The suite passes while covering nothing meaningful, because assertions check shape | medium | false confidence, exactly what G11 was written about | Criteria name specific expected values. AC-5, AC-6 and AC-9 each pin a value rather than a shape |
| Async collector tests are brittle and fail intermittently | medium | a suite nobody trusts, which is worse than none | No sleeping, no real sockets, no wall-clock timing. `_session` is stubbed and the loop is driven to completion deterministically |
| `tests/` ends up in the wheel | low | ships test data and fixtures to users | AC-2 checks the wheel contents directly |
| A future fixture captured from a live session contains an API key | low | severe and public | The committed fixture was checked. G6 applies at gate 3, and any new fixture gets the same check |
| Pinning the fixture vessel count makes the suite fragile | medium | tests fail for a legitimate mapping improvement | That is the intent. A change in what 199 fixed messages produce should require a deliberate update, not pass silently |

## 9. Out of scope

- **Coverage measurement.** Adding `pytest-cov` and a percentage target invites
  writing tests to move a number. The criteria here name behaviours instead. Worth
  revisiting once the suite exists.
- **Continuous integration.** Running the suite automatically is the obvious next
  step and a separate story. There is no point wiring CI before there is a suite.
- **Testing against the live service.** Deliberately excluded, per G15. Nothing
  here may depend on traffic, time of day or the network.
- **Input validation.** Milestone goal G3, still unstarted. This story tests what
  exists; it does not add validation. `vessels_near_port` will still accept a
  negative radius, and a test will record that as current behaviour rather than
  pretend it is correct.
- **The `mcp` 2.x migration.** S04.
- **Replacing the smoke test.** It stays. It needs no dev install and it is what
  the README tells a user to run.

## 10. Verification

```
# the suite, from a clean checkout, no key, no network
pip install -e ".[dev]"
pytest

# AC-10, proving nothing reaches the network
pytest -p no:cacheprovider          # run with networking disabled

# AC-4, proving a test can actually fail
# remove the `failures = 0` line in collector.py, run pytest, expect a named failure, restore it

# AC-2, tests must not ship
python -m build --wheel
unzip -l dist/*.whl | grep -c tests/     # expect 0

# AC-11, the recorded commands
.venv/bin/python -m pytest
.venv/bin/python -m maritime_mcp_server.smoke_test
```

**Result:** run on 2026-09-14. All eleven criteria met. Two of them failed on
first attempt and were fixed rather than reworded: see AC-5 above and divergence
D-2 below.

## 11. Divergence log

### D-1: importing `tests.conftest` only worked by accident

**When:** verifying AC-10, running the suite with sockets blocked.

**What happened:** all three of the non-mapping test modules failed at collection
with `ModuleNotFoundError: No module named 'tests'`. They imported shared builders
via `from tests.conftest import ...`.

**Why:** that import needs the repository root on `sys.path`. `python -m pytest`
puts the working directory there, so it worked during development and would have
kept working right up until someone invoked pytest any other way, including from
CI.

**Fix:** the builders moved to `tests/helpers.py`, imported as `from helpers
import ...`. pytest puts each test file's own directory on `sys.path`, so this
holds regardless of invocation. `conftest.py` now contains only fixtures.

**Confirmed** by running the suite from `/tmp` with an absolute path.

### D-2: AC-5 failed on the first check

**When:** verifying AC-5.

**What happened:** a script comparing the public functions in `ais_mapping`
against references in the test file reported `position_fields` and
`static_fields` as untested. Both are exercised through `to_record`, so the suite
was green and the coverage claim was still false.

**Why it matters more than the fix:** this is G11 in miniature. Indirect exercise
is not the same as knowing what a function returns on its own, and "the tests
pass" would have hidden it. The criterion was written to be checkable
mechanically, which is the only reason it was caught.

**Fix:** four direct tests added. The criterion was not relaxed.

### D-3: a test asserted the wrong country and the suite caught it

**When:** the first run of the mapping tests.

**What happened:** `test_position_only_record_leaves_identity_fields_null`
asserted that MMSI `314309000` carries the Bahamas flag. It is Barbados. 311 is
the Bahamas.

**Why:** I wrote the assertion from memory of an earlier S02 printout instead of
from the MID table, which is precisely what G2 forbids. The code was right and
the test was wrong.

**Worth recording** because it is the first time in this project that a mistake
was caught by a machine rather than by a person reading output. That is the whole
point of the story.
