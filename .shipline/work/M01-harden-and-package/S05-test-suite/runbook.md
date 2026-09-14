# S05 Runbook: A real test suite

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S05 | **Milestone:** M01 | **Date:** 2026-09-14

## 1. What this does

Nothing a user of the server can see changes. This story adds automated checks.

Before it, every behaviour in the project was verified by a person running a
script and reading the output carefully. That works until it does not. In the
previous story a bug got past seven separate checks and was found by someone
reading the code. Now one command checks 140 specific behaviours and says plainly
which ones broke.

You can tell it is working because `pytest` prints `140 passed` in about half a
second, and because deliberately breaking the code makes named tests fail.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.11 or newer. Tested on 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |

**No API key. No internet connection.** The suite is deliberately offline: it
runs against 199 real AIS messages that were captured once and committed to the
repository.

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| none | the tests never read the environment | not applicable |

## 3. First time setup

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` part is what installs the test runner. A plain `pip install .` gives
you a working server with no test tooling, which is what an ordinary user wants.

## 4. Run it

```bash
pytest
```

**What you should see:**

```
........................................................................ [ 51%]
....................................................................     [100%]
140 passed in 0.51s
```

Each dot is one test. To see their names, add `-v`. To run one file,
`pytest tests/test_store.py`. To run tests matching a word,
`pytest -k collector`.

## 5. Verify it works

Running the suite and seeing it pass is the weakest possible check, because a
suite that tests nothing also passes. These two checks are the real ones.

**Prove the tests can fail.** Open `maritime_mcp_server/collector.py`, find the
line `failures = 0` inside the `if await self._session():` block, and delete it.
That reintroduces a real bug from the previous story. Then:

```bash
pytest tests/test_collector.py
```

You should see two named failures:

```
FAILED test_a_productive_session_resets_the_failure_count
FAILED test_alternating_success_and_failure_never_gives_up
```

Put the line back and re-run. All 21 pass again.

**Prove it is offline.** Disconnect from the internet entirely and run `pytest`.
All 140 still pass.

## 6. When it goes wrong

Every row is something that actually happened while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'pytest'` | You ran `pip install .` rather than `pip install -e ".[dev]"` | Install with the `[dev]` extra. The quotes matter in zsh, which treats square brackets specially |
| `ModuleNotFoundError: No module named 'tests'` | Old code importing `from tests.conftest import ...` | Shared builders live in `tests/helpers.py` and are imported as `from helpers import ...`. The old form only worked when pytest was launched from the repository root |
| `zsh: no matches found: .[dev]` | zsh expanded the brackets as a glob | Quote it: `pip install -e ".[dev]"` |
| A store or server test fails with an unexpected vessel count | The fixture count is pinned to exactly 89 on purpose | If you changed the mapping layer, decide whether the new number is correct and update the test deliberately. It is meant to be a speed bump |
| Tests pass but you changed something and expected a failure | The behaviour you changed may not be covered | Run the coverage check in section 7 and see whether the function is referenced at all |
| A test is slow or hangs | Nothing here should take longer than a second in total | Check whether something opened a real socket. `_session` is stubbed in every collector test; a real connection means a stub was missed |
| The suite passes locally and fails in CI | Usually an import that relies on the working directory | Run it from another directory: `cd /tmp && pytest /full/path/to/tests`. That is how this exact bug was found |

## 7. Where things live

| What | Path |
|------|------|
| Shared fixtures: the captured messages, a filled store | `tests/conftest.py` |
| Message builders used by the test bodies | `tests/helpers.py` |
| The translation layer, 72 tests | `tests/test_ais_mapping.py` |
| The vessel store, 24 tests | `tests/test_store.py` |
| The collector and its retry policy, 21 tests | `tests/test_collector.py` |
| The server, seam and tool output, 23 tests | `tests/test_server.py` |
| 199 real captured AIS messages | `tests/data/ais_capture.json` |
| Test runner config and the `dev` extra | `pyproject.toml` |
| Project rules learned from retros, now 18 | `.shipline/guardrails.yaml` |

**A quick coverage check**, which is how a false coverage claim was caught during
this story:

```bash
python - <<'PY'
import inspect, re
from maritime_mcp_server import ais_mapping as m
src = open("tests/test_ais_mapping.py").read()
public = [n for n, o in vars(m).items()
          if not n.startswith('_') and inspect.isfunction(o)
          and o.__module__ == 'maritime_mcp_server.ais_mapping']
print("untested:", [n for n in public if not re.findall(rf'\bm\.{n}\(', src)] or "none")
PY
```

## 8. Rolling back

This story is one commit, merged into `main` and pushed. It adds tests and
changes no behaviour, so rolling it back removes checks rather than features.

To inspect the previous state without changing anything:

```bash
git checkout 46a52ba
```

Return with `git checkout main`.

To undo the merge and publish the undo:

```bash
git checkout main
git revert -m 1 <this story's merge commit>
git push origin main
```

`-m 1` keeps the state of `main` before the story. This adds a new commit rather
than rewriting history, which is the safe option on a published branch.

**One thing to know.** Rolling back also reverts `.shipline/config.json`, whose
`verify.commands` now runs the suite. After a revert, the recorded verify command
would point at a `pytest` that no longer has tests to run.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **Section 3 was verified against the local repository, not the GitHub URL.**
  The clone, venv and `pip install -e ".[dev]"` sequence was run; the same
  sequence against GitHub was not re-run from there.
- **The rollback commands in section 8 were not executed**, since running them
  would have destroyed the story. The merge commit hash is deliberately left as a
  placeholder here because it does not exist until the merge does; fill it in
  from `git log` when you need it.
- **"Disconnect from the internet and run pytest" was simulated, not performed.**
  Every socket function was replaced with one that raises, and the suite passed.
  Nobody physically pulled the network.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon. Python 3.11 through 3.13 are declared supported and untried, and CI
  does not exist to try them.
- **The suite does not cover the real websocket path.** `_session` is stubbed
  everywhere. Connect, subscribe and receive are verified only by having been run
  by hand against the live service in the previous story.
- **There is no coverage measurement.** The suite covers what five retros and
  eighteen guardrails said mattered. It does not claim to cover everything, and
  no number here would tell you how much it misses.
