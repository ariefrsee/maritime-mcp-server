# S06 Runbook: Validate tool inputs

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S06 | **Milestone:** M01 | **Date:** 2026-09-15

## 1. What this does

This server answers questions about ships for an AI assistant. Before this story
three kinds of bad question got answers that looked fine and were not.

Ask for vessels within minus five miles of a port and it told you there were
none, as though that were a fact about the sea. Ask for a ship by empty name and
it told you your query matched eighteen ships and you should be more specific,
when you had not asked for anything. And ask for vessels flagged `" malaysia "`
with a stray space and it told you there were none, when there are seven.

That last one is why this mattered. It was not a crash. It was a confident,
plausible, wrong answer, and an assistant would have passed it on to you as fact.

Now bad input is refused with an explanation, and a stray space is ignored the
way it always should have been.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.11 or newer. Tested on 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |

No API key and no network needed to see any of this. Everything below works in
snapshot mode against the bundled sample of 18 vessels.

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| `AISSTREAM_API_KEY` | only needed for live data, not for anything in this runbook | [aisstream.io](https://aisstream.io) |

## 3. First time setup

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` part installs the test runner. Quote it: zsh treats square brackets
as a pattern.

## 4. Run it

```bash
maritime-mcp-server
```

It prints nothing and waits, which is correct for this kind of server.

**You will not see this story's effects from the terminal.** The rules live in
the tool definitions that a client reads. To see them, either run the tests in
section 5 or ask an AI client a deliberately bad question, such as *"which ships
are within minus five miles of Port Klang?"*, and watch it be refused rather than
told the sea is empty.

## 5. Verify it works

**The whole suite:**

```bash
source .venv/bin/activate
pytest
```

Expect `157 passed` in under a second.

**The specific behaviour this story added:**

```bash
pytest -k "radius or blank_query or padded or whitespace_only" -v
```

Every one of those tests was confirmed to fail against the previous version
before being accepted.

**See the rules a client sees.** The valid radius range is published in the tool
schema, so an assistant knows it before calling rather than after failing:

```bash
python - <<'PY'
import asyncio, json
from maritime_mcp_server.server import mcp
async def main():
    tools = {t.name: t for t in await mcp.list_tools()}
    print(json.dumps(tools["vessels_near_port"].inputSchema["properties"]["radius_nm"], indent=2))
asyncio.run(main())
PY
```

Expect `exclusiveMinimum: 0` and `maximum: 500`.

## 6. When it goes wrong

Every row is something that actually happened while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| A radius you consider reasonable is rejected | The allowed range is above 0 and at most 500 nautical miles | The server only receives traffic for Malaysian waters, roughly 420 nautical miles corner to corner, so a wider search covers sea it never sees. Change `le=500` in `server.py` if that is wrong for you |
| `Error executing tool ...: 1 validation error` | Your input broke a schema rule | The message names the parameter. The wording is the SDK's, not this project's, and was deliberately left alone |
| A negative radius still returns an empty list | You called the Python function directly rather than through the protocol | The bounds are enforced when a client calls the tool. A direct call bypasses them. This is documented and tested, not a bug |
| A filter with a stray space returns nothing | You are on a version before this story | `pip install .` again from the current `main` |
| `search_vessels(flag="   ")` returns everything | A whitespace only filter is treated as no filter | Deliberate, and consistent with passing an empty string. Recorded as a decision rather than an accident |
| A blank vessel query says a name or MMSI is required | That is the fix | Pass part of a ship's name, or a nine digit MMSI |
| `zsh: no matches found: .[dev]` | zsh expanded the brackets | Quote it: `pip install -e ".[dev]"` |

## 7. Where things live

| What | Path |
|------|------|
| Tool signatures, bounds and descriptions | `maritime_mcp_server/server.py` |
| Filter normalisation, `_filter_text` | `maritime_mcp_server/server.py` |
| The radius bound, `Field(gt=0, le=500)` | `maritime_mcp_server/server.py`, on `vessels_near_port` |
| Tests for all of the above | `tests/test_server.py` |
| Project rules learned from retros, now 20 | `.shipline/guardrails.yaml` |

**If you add a tool or a parameter**, two things are worth copying rather than
reinventing. Put bounds in the signature with `Annotated[..., Field(...)]` so the
client reads them from the schema instead of discovering them from an error. And
if the parameter accepts a name, code or search term, normalise it through
`_filter_text` rather than comparing raw input. Guardrail G19 exists because
those two paths drifted apart once already.

## 8. Rolling back

This story is one commit, merged into `main` and pushed. It changes behaviour, so
rolling back restores three wrong answers.

To inspect the previous state without changing anything:

```bash
git checkout 9601feb
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

**What rolling back costs.** A negative radius would again report an empty sea. A
blank query would again claim it matched eighteen vessels. A filter with a stray
space would again return nothing. If something here is wrong, it is almost
certainly better to change the specific rule than to revert the story.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **The 500 nautical mile ceiling is a judgement, not a measurement.** It comes
  from the subscribed bounding box being roughly 420 nautical miles corner to
  corner. Nobody has confirmed that no legitimate question needs a wider radius.
- **Descriptions are checked for existence, not accuracy.** A test asserts every
  parameter has one. Nothing checks that what they say is still true. If the
  ceiling changes and the text does not, no test notices.
- **The Claude Desktop behaviour in section 4 was not observed in Claude
  Desktop.** Every case was driven over the same protocol from a terminal, which
  exercises the identical wire format, but no AI client was pointed at it.
- **The rollback commands in section 8 were not executed.** The merge commit hash
  does not exist until the merge does; fill it in from `git log` when you need it.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon. Python 3.11 through 3.13 are declared supported and untried.
- **Whether refusing bad input actually improves the assistant's answers is
  untested.** The reasoning is that a schema bound prevents a bad call and an
  error explains a refusal. Nobody has watched a real assistant handle either.
