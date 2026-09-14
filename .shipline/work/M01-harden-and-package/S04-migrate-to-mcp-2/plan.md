---
pipeline_state:
  story_id: S04
  milestone: M01
  title: Migrate to the mcp 2.x MCPServer API
  current_phase: plan      # plan | build | verify | test | retro | deliver | done
  phases_completed: []
  approved_by_user: false
  branch: feat/S04-migrate-to-mcp-2
  started_at: 2026-09-14
  last_updated: 2026-09-14
  guardrails_loaded: [G1, G2, G3, G4, G5, G6]
---

# S04: Migrate to the mcp 2.x MCPServer API

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

**Maturity rating: 8/10.** The migration is written and proven to work before the
story starts. The remaining two points are the wire level differences that only
show up under a client, and the fact that no automated test covers the protocol
surface, so parity rests on a harness this story has to make permanent.

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

### Step 4: Prove wire level parity

**Files touched:** none.

**What changes:** Nothing. Run the same harness from step 1 against the migrated
code and diff the two captures.

**How to check it worked:** the only difference is `serverInfo.version`, moving
from `1.30.0` to `0.1.0`. Every other field identical. This difference is
intended and is the subject of AC-5.

### Step 5: Prove it from a wheel

**Files touched:** none.

**What changes:** Nothing. Per G4, build a wheel and install it into an
environment created outside the repository, one that has never had `mcp` 1.x in
it, then run the harness against that installation.

**How to check it worked:** the clean environment resolves `mcp` 2.x from wheel
metadata alone, and the server answers a real client from a directory that is
not the project root.

### Step 6: Update the documentation

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
| AC-1 | A fresh environment built from `pyproject.toml` resolves `mcp` 2.x, and the smoke test passes against it | [ ] |
| AC-2 | `grep -rn 'FastMCP\|mcp\.server\.fastmcp' maritime_mcp_server/ pyproject.toml README.md` returns nothing | [ ] |
| AC-3 | The wire level capture after migration is identical to the capture before it, field for field, except `serverInfo.version` | [ ] |
| AC-4 | `tools/call` on `vessel_details("Kowloon Express")` returns MMSI 477055221, and `resources/read` on `vessels://all` returns 18 records, both from a wheel installed outside the repository | [ ] |
| AC-5 | `serverInfo.version` reports `0.1.0`, the project's own version, rather than the SDK's version or an empty string | [ ] |
| AC-6 | `pyproject.toml` declares an upper bound at the next major version, and installing `mcp>=3` into the project environment is reported as a conflict | [ ] |
| AC-7 | `DATA_FILE` still resolves through `importlib.resources`, and the server still answers correctly when run from a directory that is not the project root | [ ] |
| AC-8 | The failure paths are unchanged: unknown port lists the five known ports, unknown MMSI returns its error, an ambiguous name returns candidates | [ ] |
| AC-9 | `tools/compare_wire.py` is committed and runnable, so the next SDK upgrade can be checked the same way instead of by hand | [ ] |

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

**Result:** not yet run.
