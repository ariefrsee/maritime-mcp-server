# Retro S01: Make the server an installable package

**Date:** 2026-09-14
**Project:** maritime-mcp-server
**Milestone:** M01
**Branch:** `chore/S01-installable-package`

## 1. Journey

The story set out to turn a folder of scripts into something a stranger could
install and run. The mechanical work went exactly as planned. What was not
planned was the first command: installing the declared dependency produced a
version that the code cannot import, which had been true of this repository for
some time without anyone noticing, because nobody had built a fresh environment.
The story's real value turned out to be less about packaging and more about
discovering that the project was already broken for any new user.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Six steps, eight acceptance criteria, five risks. Investigation read every source file | One criterion asserted a git fact that was never checked, and was wrong |
| Build | All six steps completed. Step 1 blocked immediately on a dependency resolution problem the plan had mislocated | `mcp>=1.2.0` resolves to 2.x, which removed the module the code imports |
| Verify | Seven of eight criteria met with pasted evidence. Baseline captured before any change, compared byte for byte afterwards | Two criteria could not be checked before a commit existed |
| Test | Ten cases run after committing. Nine passed outright, one failed against a mis-specified expectation, one passed but exposed a documentation gap | The user delegated the run to the assistant, so the independent human check did not happen |

## 2. Technical findings

### 2.1 An unbounded dependency floor is a time bomb, not a convenience

**What happened:** `requirements.txt` said `mcp>=1.2.0`. Creating a fresh
virtual environment and installing it pulled `mcp` 2.2.0. The server then failed
to import at all:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where
FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and
other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
or pin 'mcp<2' to keep running v1 code.
```

**Why:** the upstream project shipped a major version with a renamed public API.
A floor with no ceiling opts you in to every future breaking change
automatically. The failure mode is nasty because it is invisible to anyone with
a working environment: existing installs keep running on the old version, while
every new clone breaks. This repository had been in that state since `mcp` 2.0
shipped.

**Fix:** `dependencies = ["mcp>=1.2.0,<2"]` in `pyproject.toml`.

```
$ pip show mcp | grep -i version
Version: 1.30.0
$ python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

Worth knowing: pip warns about the conflict but still installs a violating
version if you ask it to directly. The ceiling protects a clean resolve, not a
forced one.

```
ERROR: pip's dependency resolver does not currently take into account all the
packages that are installed. maritime-mcp-server 0.1.0 requires mcp<2,>=1.2.0,
but you have mcp 2.2.0 which is incompatible.
```

### 2.2 Locating package data by walking up the filesystem only works in a checkout

**What happened:** `DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "vessels.json"`
walks out of the package into a sibling directory. That directory exists in a git
clone and nowhere else. Installed from a wheel, the path resolves to somewhere
inside `site-packages` that contains nothing.

**Why:** the layout conflated "where the source lives" with "where the package
is". They are the same only during development, which is exactly when you would
never notice.

**Fix:** move the data inside the package, declare it as package data, and
resolve it through the import system rather than the filesystem.

```python
from importlib.resources import files
DATA_FILE = files(__package__).joinpath("data/vessels.json")
```

```
$ w/bin/python -c "from maritime_mcp_server.server import DATA_FILE; print(DATA_FILE)"
/tmp/.../w/lib/python3.14/site-packages/maritime_mcp_server/data/vessels.json
```

### 2.3 An editable install cannot tell you whether packaging works

**What happened:** `pip install -e .` succeeded and every check passed, while the
question the step was meant to answer, does the dataset ship, remained untested.
Editable installs point at the source tree, so missing package data declarations
are invisible.

**Why:** the thing being tested and the thing being used were the same files.

**Fix:** build a real wheel, inspect its namelist, and install it into an
environment created outside the repository.

```
$ unzip -l dist/maritime_mcp_server-0.1.0-py3-none-any.whl | grep vessels.json
     4303  07-20-2026 07:59   maritime_mcp_server/data/vessels.json
$ w/bin/python -c "import json; from maritime_mcp_server.server import search_vessels; print(len(json.loads(search_vessels())))"
18
```

### 2.4 `git log --follow` proves nothing until the rename is committed

**What happened:** step 2 asked for `git log --follow` on the renamed file as its
check. It returned empty output. This read as a failure, and was not one.

**Why:** `--follow` reconstructs renames from commit history. A staged rename is
not history yet. The available evidence at that point was `git status` reporting
`R`, which is a different and weaker claim.

**Fix:** move the check after the commit. `git show --stat -M` on the commit is
the direct evidence:

```
{src => maritime_mcp_server}/server.py             |   9 +-
{data => maritime_mcp_server/data}/vessels.json    |   0
```

## 3. What went wrong

- **The plan asserted a git fact without running the command.** AC-5 said
  `--follow` would reach `e0cd9ad` and that `server.py` had three commits of
  history. Neither was ever true. `e0cd9ad` added only `.gitignore`, `README.md`
  and `requirements.txt`; both moved files were created in `c0de61f`. The
  criterion was checkable in two seconds during planning and was not checked.
  TC5 then "failed" for a reason that had nothing to do with the work.
- **The plan's top risk was mislocated.** It named the Python version as the
  thing that would block the story. The interpreter was fine. The dependency
  specifier was the hazard, and it was sitting in a file the investigation had
  already read and described as "one line, no version ceiling, no Python floor",
  without drawing the conclusion.
- **The plan declared a version ceiling out of scope using a reason that was
  false within one command.** The stated grounds were "no compatibility break
  has been observed". No one had looked.
- **Three acceptance criteria were written so they could not be evaluated at the
  point the pipeline reaches them.** AC-1, AC-5 and AC-7 all require a commit,
  and the commit is gated behind the retro. This forced either proxy checks or
  a reordering, and in the end the commit was brought forward.
- **Build artifacts were nearly committed.** `dist/`, `build/` and `*.egg-info/`
  are produced by the packaging steps this story added, and `.gitignore` covered
  none of them. Caught while staging.
- **Four `.DS_Store` files were staged.** The first attempt to exclude them used
  a single path and missed three nested copies. Caught by reading the staged
  list rather than trusting the exclusion.
- **The independent human test pass did not happen.** The user chose to have the
  assistant run the script. The ticks in `testscript.md` were produced by the
  same party that wrote the code, which is recorded there plainly but is a
  genuinely weaker check than the gate intends.

## 4. What went right

- **Capturing the byte level baseline before touching anything.** Eight tool and
  resource outputs were serialized before step 3 and compared with `diff -r`
  afterwards. This turned AC-8 from an assertion into evidence, and it cost
  about a minute.
- **Step 1 existed only to fail fast.** The plan deliberately front loaded the
  riskiest unknown into a step that changed no files. The risk it actually found
  was a different one, but the structure still worked: the blocker surfaced in
  the first command rather than after five steps of rework.
- **Driving a real JSON-RPC handshake rather than importing the functions.**
  Importing proves the module loads. Only the handshake proved the server
  answers a client, and it caught nothing this time but is the check that would
  have caught a broken entry point.
- **Reading the staged file list before committing** rather than trusting
  `git add -A`.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G1 | Every dependency gets an upper bound at the next major version | critical | backend |
| G2 | Never write a checkable fact into a plan without running the command that checks it | high | backend, frontend, mobile, infrastructure, content, ops |
| G3 | Package data is resolved through the import system, never by walking the filesystem from `__file__` | high | backend |
| G4 | Packaging is verified with a built artifact installed outside the repository, never with an editable install | high | backend |
| G5 | An acceptance criterion must be evaluable at the pipeline phase that checks it | medium | backend, frontend, mobile, infrastructure, content, ops |
| G6 | Read the staged file list before every commit | medium | backend, frontend, mobile, infrastructure, content, ops |

Considered and rejected as guardrails:

- "Do not let the assistant run its own test script." This is the user's call to
  make per story, not a standing rule, and Shipline already records who ran it.
- "Add `.DS_Store` to `.gitignore`." Too specific to be a rule. G6 covers the
  general case, which is that the staged list gets read.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **Migrate to the `mcp` 2.x API.** `FastMCP` is now `MCPServer`, imported from
  `mcp.server.mcpserver`. The `<2` pin is a holding position, not a resolution.
  This is the strongest candidate for the next story in M01, because every day
  it waits the migration gets larger.
- **The offline smoke test is still the only test.** It asserts four things and
  exits on the first failure. Milestone goal G2 is unstarted.
- **No input validation anywhere.** `vessels_near_port` accepts a negative
  `radius_nm` and returns an empty list rather than an error. Milestone goal G3
  is unstarted.
- **Version is hardcoded at `0.1.0` in `pyproject.toml`.** There is no release
  process and no changelog. Fine for now, worth a decision before any publish.
- **`license = "MIT"` is declared in `pyproject.toml` but there is no LICENSE
  file in the repository.** That mismatch should be resolved before publishing.
