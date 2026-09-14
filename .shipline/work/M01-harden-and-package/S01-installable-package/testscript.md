# S01 Test Script: Make the server an installable package

**Story:** S01 | **Branch:** `chore/S01-installable-package` | **Date:** 2026-09-14

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails. Do not tick a case you did not actually run.

Every acceptance criterion in the plan must be covered by at least one case.

A note on what I already ran. During build I verified AC-1 through AC-4 and AC-6
through AC-8 with the evidence recorded in section 6 of the plan. The cases below
are not a re-run for its own sake. TC1, TC2 and TC8 deliberately start from a
real git clone, which I could not do because nothing is committed yet, and that
is the one path a stranger will actually take. TC5 and TC9 could not be run at
all before a commit exists.

Scratch space for these cases:

```bash
export TD=$(mktemp -d)
echo "working in $TD"
```

Delete it when you are done: `rm -rf "$TD"`.

---

## Prerequisites

- [ ] On branch `chore/S01-installable-package`
- [ ] `git status` shows the staged renames and the new `pyproject.toml`
- [ ] Python 3.10 or newer available as `python3`

---

## Test cases

### TC1: A stranger can install from a clean clone

**Covers:** AC-1

**Purpose:** The headline promise of the story. If this fails, nothing else matters.

**Steps:**
1. `cd "$TD" && git clone /Users/ariefrse/maritime-mcp-server fromclone`
2. `cd fromclone && git checkout chore/S01-installable-package`
3. `python3 -m venv .venv && source .venv/bin/activate`
4. `pip install .`
5. `which maritime-mcp-server`

**Expected:** The install completes without error. `which` prints a path ending
`.venv/bin/maritime-mcp-server`.

**Note:** this case only works after gate 3. Before the commit, the clone
contains the old `src/` layout and `pip install .` will fail for want of a
`pyproject.toml`. If you are running the script before committing, mark this
blocked rather than failed.

**Result:** [ ] Pass [ ] Fail [ ] Blocked, not yet committed

**Notes:**

---

### TC2: The README works when followed literally

**Covers:** AC-7

**Purpose:** Documentation that does not work is worse than no documentation. Read
the README as though you have never seen this repo and do exactly what it says,
nothing more.

**Steps:**
1. In the clone from TC1, open `README.md`.
2. Follow the Setup section verbatim. Do not use knowledge from this conversation.
3. Follow the "Verify it works (offline)" section verbatim.
4. Follow the "Run the server" section verbatim. Press Ctrl+C to stop it.
5. Read the "Use it from Claude Desktop" JSON block.

**Expected:** Every command works as printed. The offline check ends with
`All smoke checks passed.` The server starts and sits waiting rather than
exiting with a traceback. The JSON block contains no `cwd` key and no `args`
array.

**Result:** [ ] Pass [ ] Fail [ ] Blocked, not yet committed

**Notes:**

---

### TC3: The working directory genuinely does not matter

**Covers:** AC-2

**Purpose:** This is the bug the story exists to kill. The old code found its
dataset by walking up out of the package, so running from the wrong directory
gave you a server that started and then failed on first use.

**Steps:**
1. With the environment from TC1 active, `cd /` so you are as far from the repo as possible.
2. Run:
   ```bash
   python -c "import json; from maritime_mcp_server.server import vessel_details; print(json.loads(vessel_details('Kowloon Express'))['mmsi'])"
   ```

**Expected:** prints `477055221`. No traceback, no file not found.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC4: It speaks the protocol, not just Python

**Covers:** AC-2

**Purpose:** Importing the functions proves the code loads. It does not prove the
MCP server actually answers a client. This drives a real handshake.

**Steps:**
1. From any directory, with the TC1 environment active:
   ```bash
   printf '%s\n' \
   '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
   '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
   '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"vessel_details","arguments":{"query":"Kowloon Express"}}}' \
   | maritime-mcp-server 2>/dev/null
   ```

**Expected:** Two JSON lines. The first has `"serverInfo"` naming
`maritime-vessel-data`. The second contains `477055221` inside the text content.

**If you see only one line:** that is a harness race, not a product fault. The
server can exit on stdin EOF before handling the last request. Re-run. I hit this
during build and it is documented in the retro.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC5: File history survived the rename

**Covers:** AC-5

**Purpose:** A rename done as delete plus add makes the history of the only two
source files in this project unreachable. This is the case I could not run.

**Steps:**
1. `cd /Users/ariefrse/maritime-mcp-server`
2. `git log --follow --oneline maritime_mcp_server/server.py`
3. `git log --follow --oneline maritime_mcp_server/data/vessels.json`

**Expected:** Both reach back to `e0cd9ad Scaffold maritime MCP server project`.
Three commits for `server.py`.

**Note:** this requires the commit from gate 3 to exist. Before that, `--follow`
on a staged rename returns nothing, which is not a failure.

**Result:** [ ] Pass [ ] Fail [ ] Blocked, not yet committed

**Notes:**

---

### TC6: The dependency ceiling holds

**Covers:** AC-1, AC-3

**Purpose:** This is the failure that stopped build dead. Unbounded `mcp>=1.2.0`
resolves to 2.x, where `FastMCP` no longer exists. If the ceiling is ever lost,
every fresh install breaks while every existing one keeps working, which is the
worst kind of bug to diagnose.

**Steps:**
1. With the TC1 environment active: `pip show mcp | grep -i version`
2. Deliberately try to break it: `pip install "mcp>=2" 2>&1 | tail -5`
3. Then confirm the damage and undo it: `python -c "import mcp.server.fastmcp"`, then `pip install .`

**Expected:** Step 1 shows a 1.x version, 1.30.0 at time of writing. Step 2 is
either refused as a conflict or installs 2.x. If it installs, step 3's import
raises `ModuleNotFoundError` with a message about `FastMCP` being renamed to
`MCPServer`, and reinstalling the project restores 1.x.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC7: Nothing still refers to a package called `src`

**Covers:** AC-4

**Steps:**
1. `cd /Users/ariefrse/maritime-mcp-server`
2. `grep -rn 'src\.' README.md maritime_mcp_server/ pyproject.toml .shipline/config.json`

**Expected:** no matches.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC8: A built wheel is self contained

**Covers:** AC-3

**Purpose:** Editable installs hide missing package data. Only a real wheel in a
clean environment shows it.

**Steps:**
1. `cd /Users/ariefrse/maritime-mcp-server && .venv/bin/python -m build --wheel`
2. `unzip -l dist/maritime_mcp_server-0.1.0-py3-none-any.whl | grep vessels.json`
3. `cd "$TD" && python3 -m venv w && w/bin/pip install /Users/ariefrse/maritime-mcp-server/dist/*.whl`
4. `w/bin/python -c "import json; from maritime_mcp_server.server import search_vessels; print(len(json.loads(search_vessels())))"`

**Expected:** Step 2 lists `maritime_mcp_server/data/vessels.json`. Step 4 prints `18`.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC9: The recorded verify command runs

**Covers:** AC-6

**Purpose:** Shipline runs this command unattended in later stories. If it is
wrong, every future story reports a false failure.

**Steps:**
1. `cd /Users/ariefrse/maritime-mcp-server`
2. Read `.shipline/config.json`, find `verify.commands`, and paste it exactly as written.

**Expected:** `.venv/bin/python -m maritime_mcp_server.smoke_test` runs and ends
with `All smoke checks passed.`

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

### TC10: Behaviour did not change

**Covers:** AC-8

**Purpose:** This story was supposed to move files, not change what the tools
return. Spot check the failure paths, since those are the easiest to break by
accident.

**Steps:**
1. With the TC1 environment active, from any directory:
   ```bash
   python -c "
   from maritime_mcp_server.server import vessels_near_port, vessel_details
   print(vessels_near_port('Nowhere'))
   print(vessel_details('999999999'))
   print(vessel_details('Seri')[:80])
   "
   ```

**Expected:**
- Unknown port returns an error object listing the five known ports.
- Unknown MMSI returns `{"error": "No vessel found matching '999999999'."}`.
- `Seri` matches more than one vessel and returns an error with a `candidates` list.

**Result:** [ ] Pass [ ] Fail

**Notes:**

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC1, TC6 | [ ] |
| AC-2 | TC3, TC4 | [ ] |
| AC-3 | TC6, TC8 | [ ] |
| AC-4 | TC7 | [ ] |
| AC-5 | TC5 | [ ] |
| AC-6 | TC9 | [ ] |
| AC-7 | TC2 | [ ] |
| AC-8 | TC10 | [ ] |

## Outcome

- [ ] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Failures:**
