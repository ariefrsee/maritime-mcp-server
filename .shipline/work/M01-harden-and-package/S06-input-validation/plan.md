---
pipeline_state:
  story_id: S06
  milestone: M01
  title: Validate tool inputs
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S06-input-validation
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14, G15, G16, G17, G18]
---

# S06: Validate tool inputs

## 1. What this is

Three questions currently get answers that are wrong, misleading, or both, and
nothing tells you.

Ask for vessels within minus five miles of Port Klang and you are told there are
none, as though that were a fact about the sea. Ask for a vessel by empty name
and you are told your query matched eighteen ships and you should be more
specific, when you did not ask for anything. Ask for vessels flagged
`" malaysia "` with a stray space and you are told there are none, when there are
seven.

That last one is the reason this story matters. It is not a crash. It is a
confident, plausible, wrong answer, and an AI assistant will relay it to you as
fact.

## 2. Maturity assessment

Small and well understood, because the investigation is done. What raises the
risk above the size is that this is the first story to deliberately change how
the tools answer.

### What the protocol already handles

**This was checked before planning, and it removes most of the obvious work.**
Every bad *type* is already rejected by the MCP layer before reaching this code:

| Sent over the wire | Result today |
|--------------------|--------------|
| `radius_nm: "abc"` | `isError`, validation error, function never runs |
| `radius_nm: null` | `isError`, validation error |
| `port: 123` | `isError`, validation error |
| `port` missing entirely | `isError`, validation error |
| `query: null` | `isError`, validation error |
| `vessel_type: 123` | `isError`, validation error |

Direct Python calls do raise `TypeError` and `AttributeError` on these, but no
client makes direct Python calls. **Type validation is not the work.**

### What is actually broken

| Sent over the wire | Result today | Why it is wrong |
|--------------------|--------------|-----------------|
| `radius_nm: -5` | `ok`, 0 matches | A negative radius is meaningless. Reporting an empty sea is a false statement about the world |
| `radius_nm: 0` | `ok`, 0 matches | Same |
| `query: ""` | `ok`, "matched 18 vessels; be more specific" | You asked for nothing. Being told your nothing was ambiguous is nonsense |
| `query: "   "` | same | Same |
| `flag: " malaysia "` | **`ok`, 0 matches** | **There are seven.** A silent wrong answer, the worst failure in this list |

The whitespace bug is an asymmetry, not an oversight in general: `vessels_near_port`
already strips and lowercases its `port`, so `" port klang "` works. The three
filters on `search_vessels` do not.

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Three tools and a resource | working, signatures unchanged by this story | `server.py` |
| Port lookup that already normalises | `key = port.strip().lower()` | `server.py` |
| Error shape with provenance | `{"data": {...}, "error": "..."}` already used for unknown ports | `server.py` |
| 140 tests | including one that records the negative radius bug as current behaviour | `tests/` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| A bound on `radius_nm` in the schema | low | low. Proven to work during planning |
| Rejecting a blank `query` | low | low |
| Normalising the `search_vessels` filters | low | **medium.** It changes answers, which is the point, but silently changing answers is how this project got into trouble before |
| Tool descriptions that tell the client the valid ranges | low | low, and probably the highest value part |

**Maturity rating: 6/10.** Nothing exists, but the mechanism is proven, the three
defects are identified precisely rather than guessed at, and a test suite exists
to catch what changes.

### The mechanism, verified during planning

FastMCP turns a `pydantic` constraint in the signature into a JSON schema
constraint the client can read:

```python
radius_nm: Annotated[float, Field(gt=0, le=500,
    description="Search radius in nautical miles, greater than 0.")] = 30.0
```

produces:

```json
{"default": 30.0, "exclusiveMinimum": 0, "maximum": 500, "type": "number",
 "description": "Search radius in nautical miles, greater than 0."}
```

and rejects `-5`, `0` and `1e9` before the function body runs. This is better
than a hand written check, because the client learns the valid range from the
schema **before** calling rather than from an error afterwards.

## 3. Guardrails that apply

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G2 | Never write a checkable fact into a plan without running the command that checks it | Every row in both tables above came from probing the running server over stdio, not from reading the code. The schema constraint mechanism was proven with a throwaway server before being planned |
| G5 | A criterion must be evaluable at the phase that checks it | Every criterion below runs during build, offline |
| G8 | Never present data in a field the source did not supply | The reason a negative radius must not return an empty list: an empty list is a claim about the sea, not about the question |
| G9 | A change to an output contract is a gate decision, not a build decision | **This story changes what three calls return.** It is the point of the story, and it is still a contract change. Named at the gate, not buried in a build report |
| G11 | A criterion that checks shape must not stand in for one that checks behaviour | Criteria name the exact input and the exact expected output, not "returns an error" |
| G17 | Prove a test can fail before trusting that it passes | The whitespace fix gets a test that is confirmed to fail against today's code first |
| G18 | A claim about coverage must be checkable by a script | AC-7 enumerates every tool parameter and checks each has a documented description, rather than my reading them |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected
- [ ] PRE-2: Cut `feat/S06-input-validation`
- [ ] PRE-3: Carry forward from the S05 retro. This story closes the "milestone
      goal G3 is the only unfinished goal" item and updates the test that records
      the negative radius bug. CI, coverage measurement, the untested websocket
      path and S04 all stay open

## 5. Implementation steps

### Step 1: Bound the radius in the schema

**Files touched:** `maritime_mcp_server/server.py`.

**What changes:** `radius_nm` becomes
`Annotated[float, Field(gt=0, le=500, description=...)]`. The upper bound is not
arbitrary: the bounding box this server subscribes to spans roughly 420 nautical
miles corner to corner, so anything above 500 is asking about water the server
never sees, and silently returning everything it holds would misrepresent that.

**How to check it worked:** over the wire, `-5`, `0` and `1000` all return
`isError` naming `radius_nm`, and `30` still works. The generated schema contains
`exclusiveMinimum: 0` and `maximum: 500`.

### Step 2: Reject a query that asks for nothing

**Files touched:** `maritime_mcp_server/server.py`.

**What changes:** `vessel_details` returns a structured error when `query` is
empty or only whitespace, instead of reporting an ambiguous match against every
vessel. The error says what to do, in the same shape as the existing unknown port
error, and carries the provenance block like every other response.

**How to check it worked:** `""` and `"   "` both return an error mentioning that
a name or MMSI is required. `"Kowloon"` still resolves.

### Step 3: Normalise the search filters

**Files touched:** `maritime_mcp_server/server.py`.

**What changes:** `search_vessels` strips its three filters before comparing, so
`" malaysia "` matches the same five vessels as `"malaysia"`. This mirrors what
`vessels_near_port` already does with `port`.

A filter that is only whitespace is treated as absent rather than as a filter
that matches nothing, which is the same decision `""` already gets.

**How to check it worked:** `search_vessels(flag=" malaysia ")` returns the same
count as `search_vessels(flag="malaysia")`, and the test that asserts it is
confirmed to fail against today's code before the change.

### Step 4: Tell the client the rules

**Files touched:** `maritime_mcp_server/server.py`, tool docstrings and parameter
descriptions.

**What changes:** Every parameter gets a description in the schema. The AI reads
these to decide how to call a tool, so a description naming the valid ports and
the radius bounds prevents bad calls rather than merely rejecting them. The
docstrings already explain provenance and nulls; this extends the same treatment
to inputs.

**How to check it worked:** a script enumerates every parameter of every tool and
asserts each has a non-empty description. `tools/list` over the wire shows them.

### Step 5: Update the tests that recorded the old behaviour

**Files touched:** `tests/test_server.py`, new cases.

**What changes:** `test_a_negative_radius_currently_returns_nothing` was written
in S05 to record wrong behaviour as wrong, with a docstring saying it must be
updated deliberately when validation lands. This is that moment. It becomes a
test that the value is rejected.

New cases cover the blank query, the whitespace filters, and that valid input is
unaffected.

**How to check it worked:** the suite passes, and the whitespace test is
confirmed to fail against the pre-change code.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | Over the wire, `radius_nm=-5` returns `isError` naming `radius_nm`, where today it returns 0 matches | [x] |
| AC-2 | `0` and `1000` are also rejected, and `30` is accepted and returns 5 vessels | [x] |
| AC-3 | The generated schema contains `exclusiveMinimum: 0` and `maximum: 500` | [x] |
| AC-4 | A blank query returns a structured error asking for a name or MMSI, carrying provenance | [x] |
| AC-5 | `search_vessels(flag=" malaysia ")` returns the same vessels as `flag="malaysia"`, 7 against 0 before | [x] |
| AC-6 | A whitespace only filter is treated as absent, returning all 18 | [x] |
| AC-7 | Every tool parameter has a non-empty description, checked by enumeration | [x] |
| AC-8 | The new tests are demonstrated to fail against the pre-change code, per G17 | [x] |
| AC-9 | No valid call changes its answer | [x] |
| AC-10 | Every command in `verify.commands` runs as written and passes | [x] |

### Evidence

**157 tests, up from 140.** Seven new, all proven able to fail.

- **AC-1, AC-2.** Driven over stdio against the running server.
  `-5`, `0` and `1000` each return `isError` with a validation error naming
  `radius_nm`; `30` returns 5 vessels. `501` is also rejected, `500` accepted.
- **AC-3.** `tools/list` reports
  `{"default": 30.0, "exclusiveMinimum": 0, "maximum": 500, "type": "number"}`
  with a description explaining why the ceiling exists. A client sees the bounds
  without calling.
- **AC-4.** `""`, `"   "`, a tab and a newline all return
  `"A vessel name or MMSI is required..."` with `data.source` present and no
  `candidates` key. `"Kowloon"` still resolves to Kowloon Express.
- **AC-5.** `" malaysia "` and `"malaysia"` both return 7, and the same MMSIs in
  the same order. Before the change: 0 and 7.
- **AC-6.** `flag="   "` returns 18, as does `vessel_type="  ", status="  "`.
- **AC-7.** Enumerated over `tools/list` rather than read: all six parameters
  across three tools carry a description, `missing: none`.
- **AC-8.** Two separate reversions, each isolating one change. Removing filter
  normalisation failed three named tests. Removing the blank query check failed
  four. Restored, and all 157 pass.
- **AC-9.** The 140 pre-existing tests pass unchanged, except the one S05 wrote
  specifically to be replaced here.
- **AC-10.** `pytest` then the smoke test, both verbatim, both pass.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| none | |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/server.py` | schema constraints, blank query rejection, filter normalisation, parameter descriptions |
| `tests/test_server.py` | update the recorded bug, add cases for the three fixes |
| `README.md` | note the radius bounds |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **This changes what three calls return**, which is a contract change | certain | a client relying on an empty list for a negative radius now gets an error | Raised at the gate per G9. Nothing outside this repository consumes these tools. The old behaviour was a false statement about the world, so preserving it has no value |
| The 500 nautical mile ceiling is arbitrary and rejects a legitimate query | low | a user asking a wide question gets an error | The bound is derived from the subscribed bounding box, roughly 420 nm corner to corner. Stated in the description so the client sees it. If it proves wrong it is a one line change |
| Stripping filters changes results for someone relying on the old behaviour | very low | a query that returned nothing now returns vessels | That is the fix. Returning nothing was wrong |
| Treating a whitespace-only filter as absent is the wrong call | medium | `flag="   "` returns everything rather than nothing | Defensible either way. Chosen for consistency with `""`, which already means "no filter". Recorded here as a decision rather than an accident |
| Descriptions drift from behaviour over time | medium | the client is told rules that no longer hold | AC-7 checks descriptions exist, not that they are true. That gap is real and is not solved by this story |

## 9. Out of scope

- **Type validation.** Already handled by the MCP layer, demonstrated above. Adding
  hand written type checks would duplicate the protocol and only affect direct
  Python calls, which no client makes.
- **Improving the SDK's validation error text.** `Error executing tool ...: 1
  validation error` is the SDK's wording. Rewriting it would mean intercepting
  the framework's errors, which is a bigger change than this story.
- **Validating the resource.** `vessels://all` takes no arguments.
- **Rate limiting or abuse protection.** Not an input validation concern, and this
  server runs locally under one user.
- **The `mcp` 2.x migration.** S04, and still the last planned story after this.
- **CI.** Still unstarted and still the obvious next infrastructure step.

## 10. Verification

```
# the suite
.venv/bin/python -m pytest
.venv/bin/python -m maritime_mcp_server.smoke_test

# over the wire, where it actually matters
# expect isError for -5, 0 and 1000; 5 vessels for 30
# expect a structured error for an empty query
# expect " malaysia " and "malaysia" to agree

# AC-3, the schema a client reads
# tools/list, then read inputSchema.properties.radius_nm

# AC-8, proving a test can fail
# stash the change, run the whitespace test, expect failure, restore
```

**Result:** run on 2026-09-15. All ten criteria met, with the behaviour checked
over the real protocol rather than by calling functions directly.

## 11. Divergence log

### D-1: the plan said five vessels and there are seven

**When:** immediately after cutting the branch, running the G17 check that the
bug existed.

**What happened:** the plan asserted that `flag=" malaysia "` should return five
vessels. It returns seven. The five was the Port Klang radius result, carried
over from a different probe.

**Why it matters:** this is the third time in this project that G2 has caught a
number written from memory rather than from a command, and the first time it
happened inside the story that exists to stop misleading answers. The plan was
corrected before any code was written.

### D-2: validation lives at the protocol boundary, not in the function

**When:** step 5, deciding how to write the test.

**What happened:** a `pydantic` constraint in the tool signature is enforced by
FastMCP when it validates a `tools/call`. A direct Python call skips it entirely:

```
radius -5 direct  -> 0 matches (constraint NOT applied)
radius -5 via mcp -> rejected: ToolError
```

**Why it matters:** the acceptance criteria were written as "over the wire",
which turned out to be load bearing rather than stylistic. A test calling
`vessels_near_port(-5)` directly would have passed against both the old and new
code and proved nothing.

**Effect:** the rejection tests go through `mcp.call_tool`. A further test records
the bypass explicitly, because the smoke test calls these functions directly and
therefore gets no validation.

**Not fixed here.** Duplicating the bounds inside the function would make the
schema and the check two places to keep in step. The honest answer is that this
is a limitation, written down rather than papered over.
