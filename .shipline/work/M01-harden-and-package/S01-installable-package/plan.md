---
pipeline_state:
  story_id: S01
  milestone: M01
  title: Make the server an installable package
  current_phase: done      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test, retro, runbook, deliver]
  approved_by_user: true
  branch: chore/S01-installable-package
  started_at: 2026-09-14
  last_updated: 2026-09-14
  guardrails_loaded: []   # none existed at plan time; S01 produced G1 to G6
---

# S01: Make the server an installable package

## 1. What this is

Today someone who wants to run this server has to clone the repository, build a
virtual environment by hand, and then write two absolute paths into their MCP
client config, one for the interpreter and one for the working directory. If they
get the working directory wrong the server starts and then fails the moment a
tool tries to read the dataset. After this story they install the project once
and launch it by name, from anywhere, with no paths and no working directory.
The dataset travels with the code instead of being found by walking up the
filesystem.

## 2. Maturity assessment

The tool logic is finished and stable. What is missing is everything that turns a
folder of scripts into a distributable unit, and the current layout actively
fights that: the import package is literally named `src`, and the data file is
located by walking out of the package into a sibling directory that only exists
in a git checkout.

### Dependencies

| Dependency | Status | What it provides |
|------------|--------|------------------|
| `mcp` (FastMCP) | declared in `requirements.txt` as `mcp>=1.2.0`, not installed anywhere on this machine | the `FastMCP` server, the `@mcp.tool()` and `@mcp.resource()` decorators, the stdio transport |
| Python interpreter | only `python3` 3.14.6 is on PATH. There is no `python`, and no `.venv` in the repo | the runtime. Note the mismatch with the README and with the recorded verify command, both of which say `python` |
| A build backend | absent | needed by `pip install .`. `setuptools` is the low risk choice here |

### What already exists

| Component | Status | Location |
|-----------|--------|----------|
| Three MCP tools | complete and working | `src/server.py` lines 54 to 114 |
| `vessels://all` resource | complete | `src/server.py` lines 117 to 120 |
| A `main()` entry function | already exists, already correct for a console script | `src/server.py` lines 123 to 124 |
| Offline smoke test | complete, asserts real values | `src/smoke_test.py` |
| Dataset | 18 records, uniform shape, string MMSIs | `data/vessels.json` |
| Dependency list | one line, no version ceiling, no Python floor | `requirements.txt` |

### What is missing

| Component | Complexity | Risk |
|-----------|------------|------|
| `pyproject.toml` with metadata, `requires-python` and a console script | low | low |
| A real package name. `src` cannot be distributed, it collides with every other src layout project | low mechanically, wide blast radius | medium |
| Data shipped as package data rather than found by `parent.parent` | medium | medium, this is the failure that only shows up after install |
| A working environment. Nothing can be verified until `mcp` installs | low | medium, `mcp` may not yet support Python 3.14 |

**Maturity rating: 4/10.** The behaviour is done and needs no changes, but almost
nothing about the current file layout survives packaging untouched, and the
recorded verify command does not run today.

## 3. Guardrails that apply

`.shipline/guardrails.yaml` has an empty `guardrails` list. None apply, because
this is the first story in the project and no retro has produced one yet.

| ID | Rule | How it constrains this story |
|----|------|------------------------------|
| none | | |

## 4. Prerequisites

Do these before writing any code. Do not merge them into the implementation
steps.

- [ ] PRE-1: Confirm the current branch is not protected. `main` is protected in `config.json`
- [ ] PRE-2: Cut `chore/S01-installable-package`
- [ ] PRE-3: No previous story exists, so there are no carried over retro items

## 5. Implementation steps

### Step 1: Establish a working baseline

**Files touched:** none. Environment only.

**What changes:** Create `.venv` with `python3 -m venv .venv` and install the
current dependency set into it. `.venv/` is already in `.gitignore`, so nothing
is committed.

**How to check it worked:** `.venv/bin/python -m src.smoke_test` prints its four
lines and ends with `All smoke checks passed.` This is the baseline. If `mcp`
will not install on Python 3.14, stop here and report it rather than working
around it, because every later step is verified against this command.

### Step 2: Rename the import package

**Files touched:** `src/` becomes `maritime_mcp_server/`. `maritime_mcp_server/smoke_test.py` line 15.

**What changes:** `git mv src maritime_mcp_server` so history follows the files.
The relative import `from .server import ...` in the smoke test is unaffected by
the rename and should not need editing, but confirm rather than assume.

**How to check it worked:** `.venv/bin/python -m maritime_mcp_server.smoke_test`
passes, and `git log --follow maritime_mcp_server/server.py` still shows the
three original commits.

### Step 3: Move the dataset inside the package

**Files touched:** `data/vessels.json` becomes `maritime_mcp_server/data/vessels.json`. `maritime_mcp_server/server.py` line 25 and lines 38 to 41.

**What changes:** `git mv` the data file into the package. Replace the
`Path(__file__).resolve().parent.parent` lookup with
`importlib.resources.files("maritime_mcp_server").joinpath("data/vessels.json")`,
read through the traversable rather than `open()` on a path. Keep the
`@lru_cache` exactly as it is.

**How to check it worked:** the smoke test passes, and additionally
`cd /tmp && /Users/ariefrse/maritime-mcp-server/.venv/bin/python -c "from maritime_mcp_server.server import search_vessels; print(len(__import__('json').loads(search_vessels())))"` prints `18`. Running from `/tmp` is the
point of the step, since the old code depended on the working directory.

### Step 4: Add pyproject.toml

**Files touched:** new `pyproject.toml`.

**What changes:** setuptools backend. Name `maritime-mcp-server`, version
`0.1.0`, description and readme pointing at `README.md`, `requires-python = ">=3.10"`,
dependency `mcp>=1.2.0`. Declare the package explicitly and include
`data/*.json` as package data. Add
`[project.scripts] maritime-mcp-server = "maritime_mcp_server.server:main"`.
The `main()` function already exists and needs no change.

**How to check it worked:** `.venv/bin/python -m pip install -e .` completes, and
`.venv/bin/maritime-mcp-server --help` or a two second run of
`.venv/bin/maritime-mcp-server` starts the stdio server without a traceback.

### Step 5: Prove it survives a real install

**Files touched:** none.

**What changes:** Nothing in the repository. This step exists because editable
installs hide packaging bugs, in particular missing package data. Install the
`build` tool into `.venv` first, since it is a development dependency that
nothing else declares, then build a wheel and install it into a throwaway
environment outside the repository.

**How to check it worked:** from a temporary directory, a fresh venv with the
built wheel installed runs `maritime-mcp-server` and, via
`python -c "from maritime_mcp_server.server import vessel_details; ..."`, returns
the Kowloon Express record. If the dataset is missing from the wheel, this is
where it shows, and nowhere earlier.

### Step 6: Update the documentation and the recorded verify command

**Files touched:** `README.md`, `.shipline/config.json`, `requirements.txt`.

**What changes:** README setup section becomes `pip install .`. The Claude
Desktop block loses `cwd` and the absolute interpreter path, becoming the
`maritime-mcp-server` command. The offline check line becomes the new module
path. In `config.json`, `verify.commands` becomes
`[".venv/bin/python -m maritime_mcp_server.smoke_test"]`, which is both correct
after the rename and runnable on a machine with no `python` on PATH.
`requirements.txt` is reduced to a single `-e .` line so the two dependency
declarations cannot drift apart.

**How to check it worked:** follow the README from a clean clone in a temporary
directory, top to bottom, touching nothing else, and reach a running server.

## 6. Acceptance criteria

| ID | Criterion | Met |
|----|-----------|-----|
| AC-1 | `pip install .` from a clean clone succeeds and puts a `maritime-mcp-server` command on PATH | [x] see note |
| AC-2 | Running `maritime-mcp-server` from a directory that is not the repository starts the stdio server, and `vessel_details("Kowloon Express")` returns MMSI 477055221 | [x] |
| AC-3 | A built wheel, installed into an environment that has never seen the repository, contains `vessels.json` and serves all 18 records | [x] |
| AC-4 | No import path anywhere in the repository still refers to a package named `src` | [x] |
| AC-5 | ~~`git log --follow` on the moved server and data files still reaches commit `e0cd9ad`~~ **corrected during test:** reaches `c0de61f`, the commit that created them | [x] |
| AC-6 | The command in `.shipline/config.json` `verify.commands` runs as written and passes | [x] |
| AC-7 | The README, followed literally by someone who has not seen the code, produces a running server, with no absolute paths and no `cwd` setting | [x] see note |
| AC-8 | The three tools and the `vessels://all` resource return byte identical output to what they returned before this story, for the same inputs | [x] |

### Evidence

- **AC-1, AC-7.** Verified against a clean copy of the working tree with `.venv`,
  `.git`, `dist`, `build` and caches stripped, not against a git clone, because
  nothing is committed yet. `pip install .` exited 0, `maritime-mcp-server`
  landed on PATH, the offline check passed and the server started. The clone
  based form of this check is only possible after gate 3 and should be repeated
  in the test script.
- **AC-2.** A real JSON-RPC handshake was driven over stdio from `/private/tmp`.
  `initialize` returned `serverInfo {'name': 'maritime-vessel-data', 'version':
  '1.30.0'}`, `tools/list` returned all three tool names, and `tools/call` on
  `vessel_details` returned MMSI 477055221.
- **AC-3.** The wheel's namelist contains `maritime_mcp_server/data/vessels.json`.
  Installed into a venv built outside the repository, it resolved the dataset to
  `site-packages/maritime_mcp_server/data/vessels.json`, returned all 18 records,
  and pulled `mcp` 1.30.0 from wheel metadata alone, which proves the `<2` bound
  survives packaging.
- **AC-4.** `grep -rn 'src\.'` across `README.md`, the package and `pyproject.toml`
  returns nothing. The two module docstrings that still said `python -m src.server`
  were corrected during step 2.
- **AC-5.** The criterion as originally written was wrong and failed TC5. It
  asserted that `--follow` would reach `e0cd9ad` and that `server.py` had three
  commits of history. Neither was true before this story started: `e0cd9ad`
  added only `.gitignore`, `README.md` and `requirements.txt`, and both
  `server.py` and `vessels.json` were created in `c0de61f`. I wrote a
  verifiable claim into the plan without running the command that would have
  checked it. The underlying intent, that history survives the rename, is met:
  `git log --follow` crosses the rename to `c0de61f`, and `git show --stat -M`
  reports `{src => maritime_mcp_server}` for all three files and
  `{data => maritime_mcp_server/data}` for the dataset.
- **AC-6.** `.venv/bin/python -m maritime_mcp_server.smoke_test`, run exactly as
  recorded in `config.json`, printed all four lines and `All smoke checks passed.`
- **AC-8.** Eight tool and resource outputs were captured before step 3 and again
  from the clean wheel install afterwards. `diff -r` reports them byte for byte
  identical.

## 7. Files to create or modify

### New

| Path | Purpose |
|------|---------|
| `pyproject.toml` | package metadata, dependency, Python floor, package data, console script |

### Modified

| Path | Change |
|------|--------|
| `src/` to `maritime_mcp_server/` | rename via `git mv`, whole directory |
| `data/vessels.json` to `maritime_mcp_server/data/vessels.json` | moved inside the package via `git mv` |
| `maritime_mcp_server/server.py` | data file lookup switches to `importlib.resources` |
| `README.md` | setup, offline check and Claude Desktop sections |
| `requirements.txt` | reduced to `-e .` |
| `.shipline/config.json` | `verify.commands` updated to the new module path and interpreter |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `mcp` has no release supporting Python 3.14, the only interpreter on this machine | medium | blocks the entire story | Step 1 exists to hit this immediately. If it fails, stop and report, do not silently pin an older interpreter without saying so |
| The wheel builds without the dataset, because setuptools does not include package data unless told to | medium | server installs, then fails on first tool call | Step 5 tests a real wheel in a clean environment specifically to catch this. An editable install will not reveal it |
| Anyone who already wired this server into `claude_desktop_config.json` finds it broken after pulling | low, this is a personal repository | medium, silent failure at client startup | The README change is in the same story, and the old and new invocations are both documented in the commit message |
| The rename loses file history if done with delete and add instead of `git mv` | low | history for the only two source files becomes unreachable | AC-5 asserts `git log --follow` still reaches the first commit |
| `importlib.resources` behaves differently across the supported range | low | data loads on one version and not another | `requires-python = ">=3.10"` keeps the project on the modern `files()` API only |

## 9. Out of scope

- **Tests beyond the smoke test.** Milestone goal G2 is a story of its own. Adding a
  test suite and changing the package layout in one story would make a failure
  ambiguous between the two.
- **Input validation and error handling.** That is goal G3. This story must not
  change tool behaviour at all, which is what AC-8 pins down.
- **Publishing to PyPI.** Being installable and being published are different
  decisions. The metadata this story adds is what a later publish would need.
- **Continuous integration.** Nothing runs these checks automatically yet. Worth
  doing, but it belongs after there is a test suite worth running.
- **Live AIS data.** Deferred to M02 at the milestone level, for the reason
  recorded there.
- ~~**Pinning an upper bound on `mcp`.**~~ **Moved into scope during build, 2026-09-14.**
  See the divergence log in section 11. A break was observed the moment step 1 ran,
  so the stated reason for excluding it no longer holds.
- **Migrating to the `mcp` 2.x `MCPServer` API.** Discovered during step 1. It is a
  behaviour change to every tool registration in the server, which is precisely what
  AC-8 forbids in this story. It needs its own story.

## 10. Verification

```
# recorded verify command, after Step 6 updates it
.venv/bin/python -m maritime_mcp_server.smoke_test

# story specific: proves the working directory no longer matters
cd /tmp && /Users/ariefrse/maritime-mcp-server/.venv/bin/python -c \
  "import json; from maritime_mcp_server.server import search_vessels; print(len(json.loads(search_vessels())))"

# story specific: proves the wheel is self contained
python3 -m build
# then, in a fresh venv in a temporary directory
pip install /path/to/dist/maritime_mcp_server-0.1.0-py3-none-any.whl
python -c "import json; from maritime_mcp_server.server import vessel_details; \
  print(json.loads(vessel_details('Kowloon Express'))['mmsi'])"   # expects 477055221
```

**Result:** all commands above were run on 2026-09-14 and passed, except the two
that depend on a commit existing. See the evidence notes under section 6. The
`mcp` version resolved is 1.30.0 throughout, under the `<2` bound added by
divergence D-1.

## 11. Divergence log

Recorded during build. Each entry is retro material.

### D-1: `mcp>=1.2.0` resolves to 2.x, which the code cannot import

**When:** step 1, the baseline.

**Predicted:** the plan's top risk was that `mcp` would have no release supporting
Python 3.14.6 and the story would be blocked.

**What actually happened:** `mcp` installed on 3.14.6 without complaint, resolving
to 2.2.0. The import then failed:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where
FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and
other APIs changed
```

So the risk was real but mislocated. The danger was never the interpreter, it was
the unbounded dependency floor in `requirements.txt`.

**Fix:** pinned `mcp>=1.2.0,<2`, which resolves to 1.30.0 and passes the baseline.

**Scope effect:** section 9 listed an upper bound as out of scope, on the grounds
that no break had been observed. That reason was void within one command. The pin
is now required for AC-1, AC-2 and AC-3, since `pyproject.toml` must declare a
dependency and an unbounded one installs a broken package.

**Not done here:** migrating to the 2.x API. Logged as a follow-up story.
