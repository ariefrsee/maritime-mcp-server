# Retro S05: A real test suite

**Date:** 2026-09-14
**Project:** maritime-mcp-server
**Milestone:** M01
**Branch:** `feat/S05-test-suite`

## 1. Journey

Three stories shipped before this one, each verified by a person running a script
and reading the output. That worked until S03, where a bug passed seven
acceptance criteria and eight test cases and was caught by reading code. This
story closes milestone goal G2, three stories late.

The work was cheaper than expected because the code already had every seam a test
needs: an injectable clock, parsing split from the socket, a swappable data
source and a committed fixture of real traffic. None of that was designed for
testing. It arrived because each story had to verify itself somehow.

What the story actually produced, beyond 140 tests, was three caught mistakes.
Two were mine, made while writing the tests.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Every case traced to a guardrail or a retro finding, not to reading the code | The real risk was writing tests that lock in current behaviour |
| Build | Four modules, 140 tests, half a second | A test asserted the wrong country; the suite caught it |
| Verify | Eleven criteria, three of which failed first and were fixed rather than reworded | Coverage claim was false; an import worked only by accident |
| Test | Ten cases, deliberately not just re-running the suite | Two mutations performed to prove tests can fail |

## 2. Technical findings

### 2.1 A passing suite says nothing about what it skipped

**What happened:** AC-5 required every public function in `ais_mapping` to have a
test asserting a value. A script comparing the module's public functions against
references in the test file reported two untested: `position_fields` and
`static_fields`.

**Why it mattered:** both are called by `to_record`, which has five tests. The
suite was green, coverage felt complete, and the claim was false. Indirect
exercise is not knowledge of what a function returns on its own.

**Fix:** four direct tests. The criterion was written to be checked mechanically,
which is the only reason this surfaced.

```
  11 public functions, untested: ['position_fields', 'static_fields']
  -> after: untested: none
```

### 2.2 Two mutations, because a test that has never failed proves nothing

**What happened:** two criteria were verified by breaking the code on purpose.

Deleting `failures = 0` from the collector's retry loop, which is the exact S03
bug:

```
FAILED test_a_productive_session_resets_the_failure_count
FAILED test_alternating_success_and_failure_never_gives_up
```

Changing the connection warning to log the exception message instead of its type:

```
FAILED test_the_api_key_never_reaches_a_log_record
WARNING AIS connection failed (handshake failed for wss://stream?apikey=test-key-not-a-real-one), retry 1 in 0s
```

**Why:** a secret hygiene test is worthless if the code path never puts the
secret there. The only way to know the assertion bites is to make the code
careless and watch it fail.

### 2.3 An import that worked only because of how it was invoked

**What happened:** the test modules imported shared builders via
`from tests.conftest import ...`. Running the suite under a script rather than
`python -m pytest` produced `ModuleNotFoundError: No module named 'tests'` at
collection, before any test ran.

**Why:** `python -m pytest` puts the working directory on `sys.path`. Nothing
else does. The suite would have worked locally and failed the first time anyone
wired it into CI, which is the whole point of having it.

**Fix:** builders moved to `tests/helpers.py`, imported as `from helpers import
...`. pytest puts each test file's own directory on `sys.path` regardless of
invocation. `conftest.py` now holds only fixtures.

**Confirmed** by running the suite from `/tmp` against an absolute path.

### 2.4 The suite caught a mistake a human would have waved through

**What happened:** a test asserted that MMSI `314309000` carries the Bahamas
flag. It is Barbados. 311 is the Bahamas.

**Why:** written from memory of an earlier printout instead of from the MID
table, which is exactly what G2 forbids. The code was right.

**Why it is worth recording:** every previous mistake in this project was caught
by a person reading output carefully, or not caught at all. This one was caught
in 30 milliseconds by a machine that does not get tired. That is the entire case
for the story, demonstrated on the story itself.

## 3. What went wrong

- **Milestone goal G2 was three stories overdue.** Every retro since S01 named
  it. It was deferred each time because there was always something more visible
  to build, and the cost landed in S03 as a bug that passed every check.
- **The coverage claim in AC-5 was false when first checked**, and would have
  gone unnoticed if the criterion had been phrased as "the mapping layer is
  tested" rather than as something a script could evaluate.
- **A shared import worked by accident** and would have broken the first time the
  suite ran anywhere other than a developer's shell.
- **I wrote a factual assertion from memory** while writing a test suite whose
  purpose is to stop exactly that. G2 has existed since S01.
- **Ten test cases were written to verify a test suite**, which is close to
  circular. The cases that carry weight are the two mutations and the coverage
  check; the rest largely restate that the suite passes.

## 4. What went right

- **Deliberately breaking the code twice.** Neither mutation was expensive, both
  took under a minute, and together they turn "140 tests pass" into evidence
  rather than decoration.
- **Every test traces to a guardrail or a documented retro finding.** None were
  written by reading the implementation and describing it back, which is the
  standard failure of tests written after the fact.
- **Criteria written to be machine checkable.** AC-5 caught a false claim
  precisely because it named a script rather than a feeling.
- **Recording wrong behaviour as wrong.** `vessels_near_port` still accepts a
  negative radius. There is now a test that says so and a docstring explaining
  that it is not an endorsement, so goal G3 has to update it deliberately.
- **The fixture count is pinned to 89, not asserted as non-zero.** A mapping
  regression changes that number and fails.
- **The code turned out to be testable without any refactoring**, because three
  earlier stories each needed to verify themselves somehow.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G17 | Prove a test can fail before trusting that it passes | high | backend, frontend, mobile, infrastructure, content, ops |
| G18 | A claim about coverage must be checkable by a script, not by reading | medium | backend, frontend, mobile, infrastructure, content, ops |

Considered and rejected as guardrails:

- "Never import across the test package root." Too specific to pytest, and G17
  and G18 would not have caught it either. What caught it was running the suite
  an unfamiliar way, which is judgement rather than a rule.
- "Add a coverage percentage target." Deliberately rejected in the plan and still
  rejected. A percentage invites writing tests that move a number. The two
  guardrails above target the failure modes a percentage hides.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **Milestone goal G3, input validation, is the only unfinished goal in M01.**
  `vessels_near_port` accepts a negative radius and returns an empty list. There
  is now a test recording that, which will need deliberate updating.
- **S04, the `mcp` 2.x migration, is the last planned story.** Its plan predates
  S02, S03 and S05, so re-read section 5 against the current `server.py`, which
  now has a lifespan hook and a source seam it did not have then. The suite makes
  that migration far safer than it would have been.
- **There is still no CI.** The suite exists, runs in half a second, and needs no
  key or network, which is exactly the shape that makes CI worth wiring up. That
  is the obvious next infrastructure story.
- **The websocket path itself is untested.** `_session` is stubbed everywhere.
  The real connect, subscribe and receive loop is covered only by having been run
  by hand against the live service in S03.
- **No coverage measurement, by choice.** Worth revisiting now that a suite
  exists and the criteria are behaviour based rather than numeric.
- **The API key is in this session's transcript**, and a Context7 key sits in
  plaintext in `~/.zshrc`. Both still worth rotating.
