# S03 Runbook: Live AIS collector

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S03 | **Milestone:** M01 | **Date:** 2026-09-14

## 1. What this does

This is a small program that lets an AI assistant answer questions about ships.
Ask it "which tankers are at anchor near Port Klang" and it works out the answer
from vessels that are genuinely there.

Ships broadcast their position, identity and speed over the radio, a system
called AIS. This server listens to those broadcasts for Malaysian waters and
keeps track of what it hears. Before this story it could only read a fixed file
of 18 made up vessels. Now it listens to the real thing.

You can tell it is working because the answers name real ships, the positions
change if you ask again a few minutes later, and each answer says
`"source": "live"` rather than `"source": "snapshot"`.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | **3.11 or newer.** Raised from 3.10 in this story. Tested on 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |
| Internet | needed for live mode only. Snapshot mode works offline | |

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| `AISSTREAM_API_KEY` | Authenticates you to the AIS feed | Free account at [aisstream.io](https://aisstream.io). The key is shown once when created, so copy it then |

**Never put the key in a file inside the repository.** Keep it in your shell, or
in your MCP client's config, which lives outside this project. If it ever does
reach a commit, treat it as public and generate a new one.

## 3. First time setup

```bash
git clone https://github.com/Ariefrse/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Then set your key for the current terminal:

```bash
export AISSTREAM_API_KEY=paste-your-key-here
```

That lasts until you close the terminal. To make it permanent, add the same line
to `~/.zshrc`, or better, put it in your MCP client config as shown in section 4.

## 4. Run it

```bash
maritime-mcp-server
```

**What you should see:** one line saying `AIS stream connected`, then nothing
more. The terminal appears to hang.

That is correct. This server prints no banner and waits silently for an AI client
to talk to it. A silent terminal after that one line means it is working. Press
Ctrl+C to stop.

If instead you see `AISSTREAM_API_KEY is not set, so live AIS is off`, the server
is running fine but using the built in sample data. Set the key and restart.

**To actually use it,** point an AI client at it rather than running it by hand.
For Claude Desktop, edit
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS:

```json
{
  "mcpServers": {
    "maritime-vessel-data": {
      "command": "/absolute/path/to/maritime-mcp-server/.venv/bin/maritime-mcp-server",
      "env": { "AISSTREAM_API_KEY": "paste-your-key-here" }
    }
  }
}
```

Run `pwd` inside the project directory to get the absolute path. Restart Claude
Desktop fully, then ask it something like *"which vessels are near Tanjung
Pelepas right now?"*

**Give it a minute before asking.** See section 6, first row.

## 5. Verify it works

**Offline check, no key needed:**

```bash
source .venv/bin/activate
python -m maritime_mcp_server.smoke_test
```

Ends with `All smoke checks passed.` The `[snapshot]` tags are expected here;
this check deliberately uses the bundled data.

**Live check.** With the key set, start the server, **wait two minutes**, then
ask it for vessels near Tanjung Pelepas. Expect `"source": "live"`, several dozen
vessels, and names you can look up on any public ship tracking site.

The clearest proof it is live: ask twice, five minutes apart, and compare. Some
vessels will have moved. During testing, 15 of 35 ships changed position over
three minutes, by distances matching their reported speeds.

## 6. When it goes wrong

Every row is something that actually happened while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| Answers say `"source": "snapshot"` even though the key is set, right after starting | **Normal.** The server starts knowing nothing and learns about each ship only when that ship transmits. At 3 seconds it knew 0 vessels; at 150 seconds, 40; at 5 minutes, 63 | Wait a minute or two and ask again. This happens every time the server starts and cannot be avoided: the feed does not replay what you missed |
| A vessel has a position but no name, type or size | **Normal.** Ships broadcast position every few seconds and identity roughly once in ten of those | Wait. It fills in. Empty fields say `null` rather than guessing |
| A vessel reports its type but `length_m` is `null` | That ship transmitted zero hull dimensions | Working as intended. Reporting a 0 metre ship would be worse than admitting it is unknown |
| `AISSTREAM_API_KEY is not set, so live AIS is off` | The variable is not visible to the server | If using an MCP client, put it in the `env` block in section 4. Exporting it in your terminal does not reach a client-launched process |
| `Giving up on live AIS after 8 consecutive failures` | The feed was unreachable eight times running | The server keeps working from the snapshot. Check your connection, verify the key at aisstream.io, then restart the server |
| Repeated `AIS connection failed (...)` warnings | Connection dropping. The number in the message is the consecutive failure count | Harmless if it recovers; a successful session resets the count. If it climbs to 8 it stops trying |
| Vessels appear then vanish | Entries expire after 30 minutes without a transmission | Intended. A ship that stopped reporting is not still there |
| `ERROR: Package requires a different Python` on install | You are on Python 3.10 or older | This story raised the floor to 3.11, because the websocket library requires it |
| No vessels at all near Penang or Langkawi | There genuinely are none most of the time | Not a fault. Try Tanjung Pelepas or Port Klang, where the traffic is |

## 7. Where things live

| What | Path |
|------|------|
| Websocket client, subscription, reconnect | `maritime_mcp_server/collector.py` |
| Bounding box and backoff settings | `maritime_mcp_server/collector.py`, top of file |
| Server startup and shutdown hook | `maritime_mcp_server/server.py`, `_lifespan` |
| Live vessel store, merging and expiry | `maritime_mcp_server/store.py` |
| AIS translation and lookup tables | `maritime_mcp_server/ais_mapping.py` |
| Bundled 18 vessel fallback | `maritime_mcp_server/data/vessels.json` |
| Dependencies and Python floor | `pyproject.toml` |
| This story's plan, tests, retro and runbook | `.shipline/work/M01-harden-and-package/S03-live-ais-collector/` |
| Project rules learned from retros, now 16 | `.shipline/guardrails.yaml` |

## 8. Rolling back

This story is one commit, merged into `main` and pushed.

To inspect the previous state without changing anything:

```bash
git checkout 672b331
```

That is S02 as merged: everything works, but `source` is always `snapshot`.
Return with `git checkout main`.

To undo the merge and publish the undo:

```bash
git checkout main
git revert -m 1 6aab35f
git push origin main
```

`6aab35f` is this story's merge commit. `-m 1` keeps the state of `main` before
it. This adds a new commit rather than rewriting history, which is the safe
option on a published branch.

**Two things rolling back does not undo.** Anyone who installed this version on
Python 3.11 stays fine, but the older code declared support for 3.10, so the
supported-version promise changes back. And any MCP client config carrying an
`env` block with your key still holds it; remove it there if you are rolling back
because of a key concern.

**To stop live collection without rolling back anything,** just unset the key.
The server falls back to the snapshot and says so.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **The Claude Desktop configuration in section 4 was never tested in Claude
  Desktop.** The server was driven over the real MCP protocol from a terminal,
  which exercises the same wire format, but no AI client was pointed at it. The
  `env` block follows the documented format and was not observed working.
- **The rollback commands in section 8 were not executed**, since running them
  would have destroyed the story. The merge commit hash they name is real.
- **Every live figure here was measured once**, on one afternoon, in one region.
  The Strait is busy at midday and much quieter overnight. The vessel counts in
  section 6 are what was observed, not a guarantee. A quiet night could produce
  far fewer with nothing wrong.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon. Python 3.11, 3.12 and 3.13 are declared supported and untried.
- **The bounding box covers Malaysian waters only.** Ships elsewhere are not
  tracked at all, by design. Changing it means editing `DEFAULT_BOX` in
  `collector.py`; it is not configurable at runtime.
- **Long running behaviour is untested.** The longest continuous session during
  this story was about five minutes. Memory growth, or how the store behaves after
  days of traffic, is unknown.
