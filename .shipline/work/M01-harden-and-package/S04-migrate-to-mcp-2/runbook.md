# S04 Runbook: Migrate to the mcp 2.x MCPServer API

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S04 | **Milestone:** M01 | **Date:** 2026-09-15

## 1. What this does

Nothing you can see. That is the point.

This server is built on a library called the MCP SDK, which handles the
conversation between the server and an AI assistant. That library released a new
major version and renamed its main class. The project had been pinned to the old
version since the very first story, as a holding position.

This story moves to the current version. Every question you could ask before
returns the same answer, in the same shape, with one deliberate exception: when a
client asks what version this server is, it now says `0.1.0`, the project's own
version, instead of the version of the library it was built with.

You can tell it worked because the server still answers normally and
`pip show mcp` reports a 2.x version.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.11 or newer. Tested on 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| `AISSTREAM_API_KEY` | only needed for the live check in section 5 | [aisstream.io](https://aisstream.io) |

## 3. First time setup

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**If you are upgrading an existing checkout**, reinstall rather than just pulling.
The dependency changed, and an old environment will still have the old SDK:

```bash
git pull
pip install -e ".[dev]"
pip show mcp        # expect a 2.x version
```

## 4. Run it

```bash
maritime-mcp-server
```

Silence, as always. Nothing about starting the server changed.

**One cosmetic difference worth knowing.** The old SDK logged a line for every
request it handled. The new one does not. If you were used to watching that
scroll past as a sign of life, its absence is not a fault. Only
`AIS stream connected` appears now, and only when a key is set.

## 5. Verify it works

**The suite:**

```bash
source .venv/bin/activate
pytest
```

Expect `157 passed`.

**Confirm which SDK you are on:**

```bash
pip show mcp | grep -i version      # expect 2.x
python -c "from mcp.server.mcpserver import MCPServer; print('2.x API present')"
```

**The real check, and the one this story rests on.** Capture what the server says
to a client and compare it against a known good capture:

```bash
python tools/compare_wire.py --out /tmp/now.json
```

That records eleven responses: the handshake, both listings, six tool calls
including the error paths, and the resource. It runs in snapshot mode so the
output is stable and can be diffed. Compare two captures with plain `diff`.

**Live check**, if you have a key. Set `AISSTREAM_API_KEY`, start the server,
wait two minutes, and ask for vessels near Tanjung Pelepas. Expect
`AIS stream connected` and `source: live`. This is the only part no test covers.

## 6. When it goes wrong

Every row is something that actually happened while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'mcp.server.mcpserver'` | You are on the old 1.x SDK with new code | `pip install -e ".[dev]"`. Pulling alone does not change installed packages |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | The opposite: new SDK, old code | `git pull`, then reinstall |
| `AttributeError: 'Tool' object has no attribute 'inputSchema'` | Your code reads tool metadata using the old name | It is `input_schema` in 2.x. **The JSON on the wire is unchanged**, so only Python code that inspects tool objects needs this |
| `serverInfo.version` is an empty string | The server was constructed without a version | 2.x no longer fills this in. `_own_version()` supplies it. Under 1.x this field reported the SDK's version, which was misleading anyway |
| `serverInfo.version` reads `0.0.0+source` | You are running from a checkout without installing | Expected. `importlib.metadata` cannot find a package that was never installed. `pip install .` if you want the real number |
| The server logs almost nothing | 2.x is quieter. See section 4 | Not a fault |
| A client behaves differently after upgrading | Should not happen. Only `serverInfo.version` changed | Capture with `tools/compare_wire.py` and diff against the committed expectations. If something else differs, that is a real finding |

## 7. Where things live

| What | Path |
|------|------|
| The `MCPServer` import and construction | `maritime_mcp_server/server.py`, near the top |
| The version fallback, `_own_version` | `maritime_mcp_server/server.py` |
| The dependency range, `mcp>=2,<3` | `pyproject.toml` |
| Wire capture tool | `tools/compare_wire.py` |
| Project rules learned from retros, now 22 | `.shipline/guardrails.yaml` |

**Before the next SDK upgrade**, take a capture with `tools/compare_wire.py`
first. That is what turned this migration from "looks fine" into "exactly one
field differs across eleven responses", and it takes seconds.

## 8. Rolling back

This story is one commit, merged into `main` and pushed.

To inspect the previous state without changing anything:

```bash
git checkout b2ec842
pip install -e ".[dev]"      # reinstalls the old pinned SDK
```

Return with `git checkout main` and reinstall again.

To undo the merge and publish the undo:

```bash
git checkout main
git revert -m 1 <this story's merge commit>
git push origin main
pip install -e ".[dev]"
```

`-m 1` keeps the state of `main` before the story. This adds a new commit rather
than rewriting history, which is the safe option on a published branch.

**Rolling back means reinstalling.** Reverting the code without reinstalling
leaves the 2.x SDK in place with 1.x code, which fails at import. That is the
first row of section 6.

**What rolling back costs.** The project goes back to a superseded major version
of the SDK under a pin that was always a holding position. The gap only widens.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **The rollback commands in section 8 were not executed**, since running them
  would have destroyed the story. The commit they name is real; the merge commit
  hash does not exist until the merge does.
- **The wire comparison covers snapshot mode only.** Live data changes between
  captures and cannot be diffed. A behaviour difference that appears only under
  live traffic would not be caught. The live check in section 5 confirms the
  collector works, not that its output matches 1.x exactly.
- **Only `mcp` 2.1.1 and 2.2.0 were tested**, which are the only 2.x releases
  that exist. The declared range `>=2,<3` is a claim about future 2.x releases
  that cannot be tested yet.
- **The Claude Desktop path was not observed in Claude Desktop.** Everything was
  driven over the same protocol from a terminal.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon.
- **The new 2.x surface is untouched.** Middleware, prompts, completion, icons
  and the streamable HTTP transport all now exist and none are used. This story
  migrated; it did not adopt.
