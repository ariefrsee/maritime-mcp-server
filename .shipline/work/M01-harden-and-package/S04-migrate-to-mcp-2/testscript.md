# S04 Test Script: Migrate to the mcp 2.x MCPServer API

**Story:** S04 | **Branch:** `feat/S04-migrate-to-mcp-2` | **Date:** 2026-09-15

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails.

**Run by the assistant on 2026-09-15, at the user's instruction**, as in every
story. These results were produced and read by the same party that wrote the code.

This story changes the SDK underneath everything. The only question worth asking
is whether anything a client can observe has changed, so most of these cases
compare before against after rather than checking that something works.

All but TC8 run offline with no API key.

---

## Prerequisites

- [x] On branch `feat/S04-migrate-to-mcp-2`
- [x] `pip install -e ".[dev]"` has been run since the dependency change
- [x] A baseline wire capture was taken **before** any code changed

---

## Test cases

### TC1: The wire format did not change

**Covers:** AC-4, AC-9, AC-11

**Purpose:** The whole story in one case. A client must not be able to tell.

**Steps:**
1. Before changing anything, `python tools/compare_wire.py --out before.json`.
2. Migrate.
3. `python tools/compare_wire.py --out after.json`.
4. Walk both field by field and list every difference.

**Expected:** exactly one difference, `serverInfo.version`.

**Result:** [x] Pass

**Notes:** One differing field across 11 captured responses:
`initialize.serverInfo.version`, `1.30.0` to `0.1.0`. Tool schemas, the unknown
port error, the rejected radius, the blank query error and the resource are all
byte identical. The capture deliberately runs in snapshot mode so the output is
stable and comparable.

---

### TC2: The whole suite passes on the new SDK

**Covers:** AC-3

**Steps:**
1. `pytest`

**Expected:** 157 passed, with only the two `input_schema` lines changed.

**Result:** [x] Pass

**Notes:** This case found the only real breakage in the migration. Before the
fix: 155 passed, 2 failed with `'Tool' object has no attribute 'inputSchema'`.
The attribute was renamed to `input_schema` in 2.x. **The wire is unaffected**,
so no client breaks, but anything reading tool metadata in Python does.

---

### TC3: It passes on both ends of the declared range

**Covers:** AC-3, AC-8

**Purpose:** Declaring `>=2,<3` claims the code works across that whole range.
Testing only the newest release does not support that claim.

**Steps:**
1. Run the suite on `mcp` 2.1.1.
2. Upgrade to 2.2.0 and run it again.

**Expected:** 157 passed both times.

**Result:** [x] Pass

**Notes:** This was accidental. Proving the upper bound in TC4 downgraded the
environment to 2.1.1, which made the extra run free. Nothing in the plan had
thought to check it.

---

### TC4: The upper bound is enforced, not decorative

**Covers:** AC-8

**Purpose:** Guardrail G1 exists because an unbounded dependency broke this
project silently. A bound nobody has seen bite is a comment.

**Steps:**
1. `pip install "mcp>=3"`. There is no 3.x, so this proves nothing.
2. Temporarily declare `mcp>=2,<2.2` with 2.2.0 installed, then reinstall.
3. Restore `>=2,<3`.

**Expected:** step 2 downgrades the installed version.

**Result:** [x] Pass

**Notes:** Pip downgraded 2.2.0 to 2.1.1, which is direct evidence the ceiling is
enforced. The criterion as written could not be tested, so the mechanism was
tested instead rather than the criterion being quietly ticked.

---

### TC5: The version reported to clients is now the project's own

**Covers:** AC-6, AC-7

**Purpose:** Under 1.x this field reported the SDK's version, which was
misleading. Under 2.x it defaults to empty.

**Steps:**
1. Read `serverInfo` from an `initialize` response.
2. Force `version()` to raise `PackageNotFoundError` and call `_own_version()`.

**Expected:** `0.1.0` normally, `0.0.0+source` when the package is not installed.

**Result:** [x] Pass

**Notes:** The fallback is not theoretical. `PackageNotFoundError` was reproduced
during revalidation by running from a source checkout, which is what happens if
someone clones and runs without installing.

---

### TC6: Nothing in the codebase still refers to the old API

**Covers:** AC-2

**Steps:**
1. `grep -rn 'FastMCP\|mcp\.server\.fastmcp' maritime_mcp_server/ pyproject.toml README.md tests/`

**Expected:** no code references.

**Result:** [x] Pass

**Notes:** Two mentions of the word survive and are deliberate: a docstring and a
`pyproject.toml` comment recording that 1.x called this class `FastMCP`. A third
was found in the README claiming the code still targets 1.x. That one was a
falsehood rather than history, and was corrected.

---

### TC7: A clean install from a wheel works

**Covers:** AC-1, AC-5

**Steps:**
1. `python -m build --wheel`
2. Install into a venv created outside the repository.
3. From `/`, look up Kowloon Express and read the resource.

**Expected:** `mcp` 2.2.0 resolved from metadata alone, MMSI 477055221,
18 records, version `0.1.0`.

**Result:** [x] Pass

---

### TC8: The live collector still works

**Covers:** AC-10

**Purpose:** The only case no test can cover. `_session` is stubbed in every
test, so the real websocket path is verified here or not at all. Needs the API key.

**Steps:**
1. Start the server with `AISSTREAM_API_KEY` set. Wait two minutes.
2. Ask for vessels near Tanjung Pelepas.

**Expected:** `AIS stream connected` in the log, `source: live`, and real vessels.

**Result:** [x] Pass

**Notes:** 55 vessels tracked, 49 within 40nm of Tanjung Pelepas, including
VANDA SUCCESS, PILOT GP57 and CAT LAI EXPRESS. The `lifespan` hook fires the same
way under 2.x, which was the main open question after revalidation.

---

### TC9: The log is quieter, and that is not a fault

**Covers:** an observation, not a criterion

**Purpose:** Worth writing down because it looks like something is wrong.

**Steps:**
1. Compare stderr between a 1.x and a 2.x run of the same requests.

**Expected:** 2.x no longer logs `Processing request of type CallToolRequest`.

**Result:** [x] Pass, in the sense that it behaves as described

**Notes:** Under 1.x each call produced a log line. Under 2.x only
`AIS stream connected` appears. An SDK logging change, invisible on the wire, but
a quieter log reads as a dead server when you are watching stderr to see whether
anything is happening.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC7 | [x] |
| AC-2 | TC6 | [x] |
| AC-3 | TC2, TC3 | [x] |
| AC-4 | TC1 | [x] |
| AC-5 | TC7 | [x] |
| AC-6 | TC5 | [x] |
| AC-7 | TC5 | [x] |
| AC-8 | TC4 | [x] |
| AC-9 | TC1 | [x] |
| AC-10 | TC8 | [x] |
| AC-11 | TC1 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Found during the story, all recorded as divergences:**

1. **`Tool.inputSchema` became `input_schema`.** Found at revalidation, before
   the story was approved, by running the suite against a migrated scratch copy.
   The wire is unaffected. Divergence D-1.
2. **AC-8 could not be tested as written**, because `mcp` 3.x does not exist. The
   mechanism was proven with a bound that could bite rather than the criterion
   being ticked on a technicality. Divergence D-2.
3. **2.x logs less.** Cosmetic, recorded because it looks like a fault. D-3.

**What this script does not cover.** The migration was verified against snapshot
mode for the wire comparison, because live data changes between captures and
cannot be diffed. TC8 covers the live path but only that it works, not that its
output is identical to 1.x. A behaviour difference that appears only under live
data would not be caught here.
