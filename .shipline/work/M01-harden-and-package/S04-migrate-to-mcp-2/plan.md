---
pipeline_state:
  story_id: S04
  milestone: M01
  title: Migrate to the mcp 2.x MCPServer API
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: feat/S04-migrate-to-mcp-2
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19, G20]
---

# S04: Migrate to the mcp 2.x MCPServer API

> **Revalidated on 2026-09-15, before approval.** This plan was written before
> S02, S03, S05 and S06 existed. Section 2 now records what the migration was
> actually tested against rather than what was true a day ago. Two findings
> change it: `lifespan` survives, and `Tool.inputSchema` has been renamed.
>
> **Renumbered from S02 to S04 on 2026-09-14, before any code was written.**
> The user redirected the milestone toward connecting a live data source, which
> became S02. This plan is unchanged otherwise and its investigation still holds:
> the migration was built and proven in scratch during planning. Note that S02
> and S03 add a mapping layer, a vessel store and a websocket collector, so
> re-check section 5 against the shape of the code they leave behind before
> building this.

## 1. What this is

Nothing changes for anyone using the server. The tools answer the same questions
with the same words. What changes is that the project stops being held on a
superseded major version of the SDK by a pin that S01 added as a tourniquet. The
`<2` ceiling comes off and the code runs on the current release line, so future
upgrades are ordinary maintenance rather than a migration that has been deferred
for a year.

## 2. Maturity assessment

Unusually high, and I want to be precise about why rather than let the number
flatter the story. I built the entire migration in a scratch directory during
planning and ran it end to end. It is two lines. The 2.x API kept the decorator
shape, the decorators still return the undecorated function, and `run()` still
defaults to stdio.

### What the revalidation found

The whole migration was performed in a scratch copy and the **entire 157 test
suite run against it under `mcp` 2.2.0**, which was not possible when this plan
was first written because no tests existed.

**155 of 157 passed.** The two failures are real and neither is in the server:

```
AttributeError: 'Tool' object has no attribute 'inputSchema'.
                Did you mean: 'input_schema'?

FAILED tests/test_server.py::test_the_schema_publishes_the_radius_bounds
FAILED tests/test_server.py::test_every_tool_parameter_carries_a_description
```

**The rename is Python side only. The wire format is unchanged.** Compared
directly, byte for byte where it matters:

| | mcp 1.30.0 | mcp 2.2.0 |
|---|---|---|
| Tool JSON keys | `description, inputSchema, name, outputSchema` | identical |
| `radius_nm` constraint | `exclusiveMinimum: 0, maximum: 500` | identical |
| `radius_nm: -5` | rejected | rejected |
| `flag: " malaysia "` | 7 matches | 7 matches |
| `serverInfo.version` | `1.30.0` | `""` |

So **no client is affected**, and the only code to change beyond the two import
lines is two of my own tests.

Three things that did not exist when this plan was written, all verified to
survive:

- **`lifespan`.** `MCPServer.__init__` accepts it, typed
  `Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[...]]`.
  The AIS collector still starts and stops with the server.
- **`Annotated[..., Field(...)]` parameter constraints** from S06. The generated
  schema is identical and out of range values are still rejected.
- **The source seam and `set_store`** from S02. Untouched by the SDK.

The `PackageNotFoundError` risk this plan named a day ago is real and was
reproduced: `version("maritime-mcp-server")` raises when the package is not
installed, which happens when running from a source checkout.

### Dependencies

| Dependency | Status | What it provides |
|------------|--------|------------------|
| `mcp` 2.2.0 | latest release. `pip index versions mcp` lists 2.2.0 as newest, with 2.0.0 the first of the line | `MCPServer`, replacing `FastMCP` |
| Python | `mcp` 2.2.0 declares `Requires-Python: >=3.10`, identical to this project's `requires-python = ">=3.10"` | no floor change needed |

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Three tools and one resource | working, unchanged by this story | `maritime_mcp_server/server.py` |
| Smoke test calling tool functions directly | works under 2.x. Verified: the 2.x `tool()` decorator is typed `Callable[[_CallableT], _CallableT]` and returns the original function | `maritime_mcp_server/smoke_test.py` |
| Wire level comparison harness | written during S01 and extended during this plan. Drives a real client and keeps stdin open | scratch, to be committed as part of this story |
| Packaging, console script, package data | done in S01, unaffected | `pyproject.toml` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| The import and class name change | trivial, two lines | low |
| Dependency range moved from `>=1.2.0,<2` to `>=2,<3` | trivial | low |
| A version to report in `serverInfo`, which 2.x leaves empty | low | low, cosmetic but visible to clients |

**Maturity rating: 9/10.** Raised from 8 at revalidation. The migration is
written, and unlike a day ago it has been run against a 157 test suite and a
side by side wire comparison. The remaining point is that the live websocket path
is stubbed in every test, so the collector's behaviour under 2.x is inferred from
`lifespan` accepting the same argument rather than observed against the feed.

## 3. Guardrails that apply

All six are active and all six bear on this story.

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| G1 | Every dependency gets an upper bound at the next major version | The new range must be `mcp>=2,<3`. Removing the `<2` ceiling must not mean removing the ceiling. This is the guardrail S01 produced and the first story that could have violated it |
| G2 | Never write a checkable fact into a plan without running the command that checks it | Every claim in section 2 was produced by running something. The API shape, the decorator return type, the Python floor, the newest release and the `serverInfo` difference were all observed, not recalled. The migration itself was executed in scratch before this plan was written |
| G3 | Resolve package data through the import system, never by walking from `__file__` | `DATA_FILE` must keep using `importlib.resources`. The migration touches the import block directly above it, so this is exactly where a careless edit would regress S01 |
| G4 | Verify packaging with a built artifact installed outside the repository | The dependency range lives in `pyproject.toml`, so the only proof it is right is a wheel resolving `mcp` 2.x in a clean environment. An editable install would inherit the already present 2.x from this machine and prove nothing |
| G5 | An acceptance criterion must be evaluable at the phase that checks it | S01 wrote three criteria that needed a commit. None below do. Every criterion here is checkable during build |
| G6 | Read the staged file list before every commit | Applies at gate 3. The new comparison harness is the file most likely to be forgotten or accidentally excluded |

## 4. Prerequisites

- [ ] PRE-1: Confirm the current branch is not protected. `main` is protected
- [ ] PRE-2: Cut `feat/S02-migrate-to-mcp-2`
- [ ] PRE-3: Carry forward from S01 retro section 6. This story closes the first
      item, the `mcp` 2.x migration. The other four, thin test coverage, absent
      input validation, no release process and the declared but missing MIT
      LICENSE, stay open and out of scope here

## 5. Implementation steps

### Step 1: Capture the wire level baseline under 1.x

**Files touched:** none in the package. Creates `tools/compare_wire.py`.

**What changes:** Promote the scratch harness written during planning into a
committed file. It starts the server as a subprocess, keeps stdin open, sends
`initialize`, `tools/list`, `tools/call`, `resources/list` and `resources/read`,
and writes the responses to a JSON file. Keeping stdin open matters: a naive
pipe closes it and the server exits before answering, which looked like a
failure twice during S01.

Run it against the current `main` state, still on `mcp` 1.30.0, and save the
output as the baseline.

**How to check it worked:** the baseline file exists and contains three tool
names, MMSI 477055221, one resource URI and 18 records.

### Step 2: Make the migration

**Files touched:** `maritime_mcp_server/server.py`, two lines.

**What changes:**

```
-from mcp.server.fastmcp import FastMCP
+from mcp.server.mcpserver import MCPServer

-mcp = FastMCP("maritime-vessel-data")
+mcp = MCPServer("maritime-vessel-data", version=version("maritime-mcp-server"))
```

The `version` argument is not cosmetic padding. Under 1.x, `serverInfo.version`
reported `1.30.0`, which was the SDK's version rather than this server's, and was
misleading. Under 2.x it defaults to an empty string. Passing the installed
package version, read via `importlib.metadata.version`, makes it correct for the
first time.

**How to check it worked:** `grep -c FastMCP maritime_mcp_server/server.py`
returns 0. `DATA_FILE` still uses `importlib.resources`, per G3.

### Step 3: Move the dependency range

**Files touched:** `pyproject.toml`.

**What changes:** `dependencies = ["mcp>=2,<3"]`, replacing `>=1.2.0,<2`. Update
the comment above it, which currently explains why 2.x is excluded and would
become actively misleading. Per G1 the new ceiling is mandatory, not optional.

**How to check it worked:** a fresh environment built from the project resolves
`mcp` 2.2.0, and `pip install "mcp>=3"` into it reports a conflict.

### Step 4: Update the two tests that read the renamed attribute

**Files touched:** `tests/test_server.py`, two lines.

**What changes:** `tool.inputSchema` becomes `tool.input_schema` in
`test_the_schema_publishes_the_radius_bounds` and
`test_every_tool_parameter_carries_a_description`. Nothing else in the suite
touches the renamed attribute, confirmed by running it.

**How to check it worked:** all 157 pass under 2.x.

### Step 5: Prove wire level parity

**Files touched:** none.

**What changes:** Nothing. Run the same harness from step 1 against the migrated
code and diff the two captures.

**How to check it worked:** the only difference is `serverInfo.version`, moving
from `1.30.0` to `0.1.0`. Every other field identical. This difference is
intended and is the subject of AC-5.

### Step 6: Prove it from a wheel

**Files touched:** none.

**What changes:** Nothing. Per G4, build a wheel and install it into an
environment created outside the repository, one that has never had `mcp` 1.x in
it, then run the harness against that installation.

**How to check it worked:** the clean environment resolves `mcp` 2.x from wheel
metadata alone, and the server answers a real client from a directory that is
not the project root.

### Step 7: Update the documentation

**Files touched:** `README.md`, `maritime_mcp_server/server.py` docstring if it
names the SDK version, `.shipline/config.json` if the verify command changes.

**What changes:** The README's "Extending it" section mentions switching to the
HTTP/SSE transport. Under 2.x, `run()` takes
`transport: Literal['stdio','sse','streamable-http']`, so that sentence can name
the actual mechanism. Add a line recording that the project targets `mcp` 2.x.
The verify command is expected to be unchanged; confirm rather than assume.

**How to check it worked:** no reference to `FastMCP` or `mcp 1` survives
anywhere outside the S01 story folder, which is a historical record and must not
be edited.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | A fresh environment built from `pyproject.toml` resolves `mcp` 2.x, and the smoke test passes | [x] |
| AC-2 | No code references `FastMCP` or `mcp.server.fastmcp` | [x] see note |
| AC-3 | All 157 tests pass under `mcp` 2.x, with only the two `input_schema` lines changed | [x] |
| AC-4 | The wire capture after migration is identical to the one before, except `serverInfo.version` | [x] |
| AC-5 | A wheel installed outside the repository serves MMSI 477055221 and 18 records | [x] |
| AC-6 | `serverInfo.version` reports `0.1.0` rather than the SDK's version or an empty string | [x] |
| AC-7 | The version lookup falls back cleanly rather than raising when the package is not installed | [x] |
| AC-8 | The upper bound is declared and enforced | [x] see note |
| AC-9 | The S06 schema constraints still hold | [x] |
| AC-10 | The S03 collector still starts and stops with the server, verified with a real key | [x] |
| AC-11 | The failure paths are unchanged | [x] |

### Evidence

- **AC-1, AC-5.** A wheel installed into a venv created outside the repository
  resolved `mcp` 2.2.0 from metadata alone, returned MMSI 477055221 for
  Kowloon Express and 18 records from `vessels://all`, and reported version
  `0.1.0`.
- **AC-2.** No *code* reference survives. Two mentions of the word remain and are
  deliberate: a docstring and a `pyproject.toml` comment, both recording that 1.x
  called this class `FastMCP`. A third, in the README, said the code still
  targeted 1.x and was corrected; that one was a genuine falsehood rather than
  history.
- **AC-3.** 157 passed under 2.2.0, and 157 passed under 2.1.1 as well. The only
  source change outside the two import lines was `.inputSchema` to
  `.input_schema` in two tests.
- **AC-4 and AC-11.** `tools/compare_wire.py` captured 11 responses before and
  after. A field by field walk reports **exactly one difference**:
  `initialize.serverInfo.version`, `1.30.0` to `0.1.0`. Tool schemas, the
  unknown port error, the rejected radius, the blank query error and the resource
  are byte identical.
- **AC-6, AC-7.** `_own_version()` returns `0.1.0` when installed and
  `0.0.0+source` when `version()` raises `PackageNotFoundError`, which was
  reproduced in a source checkout during revalidation rather than assumed.
- **AC-8.** `mcp` 3.x does not exist, so the criterion as written could not bite.
  The mechanism was proven instead by temporarily declaring `mcp>=2,<2.2` with
  2.2.0 installed: pip **downgraded to 2.1.1**, confirming the bound is enforced
  rather than advisory. Restored to `>=2,<3` afterwards.
- **AC-9.** The captured `tools/list` is identical, so `exclusiveMinimum: 0` and
  `maximum: 500` survive, as does the rejection of `radius_nm: -5`.
- **AC-10.** The only criterion no test can cover, since `_session` is stubbed
  everywhere. With a real key the server logged `AIS stream connected` and
  answered with 55 live vessels near Tanjung Pelepas, including VANDA SUCCESS and
  CAT LAI EXPRESS.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `tools/compare_wire.py` | drives a real MCP client over stdio and captures every response, so protocol parity can be diffed rather than eyeballed |

### Modified

| Path | Change |
|------|--------|
| `maritime_mcp_server/server.py` | import, class name, and a `version` argument |
| `pyproject.toml` | dependency range `>=2,<3`, and the comment above it |
| `README.md` | note the targeted SDK line, correct the transport sentence |
| `tests/test_server.py` | two lines, `inputSchema` to `input_schema` |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| A behaviour difference exists that the five probed methods do not reach, for example prompts, completion or subscriptions | medium | a client feature silently breaks | Honest limit: this server exposes only tools and one resource, and the harness covers all of them. Methods the server does not implement cannot regress. Recorded as a known gap rather than mitigated |
| `importlib.metadata.version` raises `PackageNotFoundError` when the package is not installed, for example running from a source checkout without `pip install` | medium | the server fails at import, which is worse than a missing version string | Wrap the lookup and fall back to a literal. The fallback path must be tested, not assumed |
| Removing `<2` is done by deleting the ceiling rather than moving it | low | violates G1 the first time it applies, and reintroduces exactly the S01 failure | AC-6 tests the ceiling positively by trying to install across it |
| The wire comparison passes because both captures are broken in the same way | low | false confidence | The baseline is captured before any change and asserts concrete values, MMSI 477055221 and 18 records, not merely that the two files match |
| 2.x changes the default `mimeType` or schema generation in a way the harness records but nobody reads | low | a client parses differently | The diff is field for field and any difference beyond `serverInfo.version` fails AC-3 |

## 9. Out of scope

- **A real test suite.** Milestone goal G2, still unstarted after this story.
  `tools/compare_wire.py` is a comparison harness, not a test: it has no
  assertions of its own and is run by a human reading a diff. Calling it a test
  suite would be a lie that makes goal G2 look closer than it is.
- **Input validation.** Milestone goal G3. `vessels_near_port` still accepts a
  negative radius and returns an empty list, confirmed during S01.
- **The new 2.x surface.** `MCPServer` offers middleware, prompts, completion,
  icons, custom routes and a streamable HTTP transport. This story migrates,
  it does not adopt.
- **The missing LICENSE file.** `pyproject.toml` declares MIT and no LICENSE
  exists. Unrelated to the SDK and carried forward from S01.
- **A release or version bump.** Version stays `0.1.0`.

## 10. Verification

```
# recorded verify command
.venv/bin/python -m maritime_mcp_server.smoke_test

# wire level parity, the core of this story
python tools/compare_wire.py --out before.json     # captured on 1.x, before step 2
python tools/compare_wire.py --out after.json      # captured on 2.x, after step 2
diff before.json after.json                        # expect only serverInfo.version

# the ceiling is real, per G1 and AC-6
pip install "mcp>=3"                               # expect a reported conflict

# packaging, per G4, in an environment that never held mcp 1.x
python -m build --wheel
pip install dist/maritime_mcp_server-0.1.0-py3-none-any.whl
pip show mcp | grep -i version                     # expect 2.x
```

**Result:** run on 2026-09-15. All eleven criteria met, against both `mcp` 2.1.1
and 2.2.0.

## 11. Divergence log

### D-1: `Tool.inputSchema` was renamed, and only the tests noticed

**When:** revalidation, before the story was approved.

**What happened:** running the full suite against a migrated scratch copy gave
155 of 157 passing:

```
AttributeError: 'Tool' object has no attribute 'inputSchema'.
                Did you mean: 'input_schema'?
```

**Why it matters:** **the wire format is unchanged.** A side by side capture
shows `inputSchema` in the JSON under both versions, with identical constraints.
The rename is confined to the Python object, so no client breaks and only my own
test code needed two edits.

**Why it is the story's best argument for S05:** without a test suite this would
have shipped silently and surfaced later in whatever reads tool metadata. It was
caught in half a second by tests written for a different reason entirely.

### D-2: the upper bound could not be tested as written

**When:** verifying AC-8.

**What happened:** the criterion said installing `mcp>=3` should be reported as a
conflict. There is no `mcp` 3.x, so pip reports `No matching distribution found`,
which proves nothing about our bound.

**Fix:** temporarily declared `mcp>=2,<2.2` with 2.2.0 installed. Pip
**downgraded to 2.1.1**, which is direct evidence the ceiling is enforced.
Restored immediately.

**An unplanned benefit:** that left the environment on 2.1.1, so the suite was
run there too. It passes on both ends of the declared range rather than only on
the newest release, which nothing in the plan had thought to check.

### D-3: 2.x is quieter on stderr

**When:** AC-10, comparing live runs.

**What happened:** under 1.x each call logged `Processing request of type
CallToolRequest`. Under 2.x it does not. Only `AIS stream connected` appears.

**Assessment:** an SDK logging change, not a behaviour change, and invisible on
the wire. Recorded because a quieter log can read as a broken server when you are
watching stderr to see whether anything is happening.
