# S01 Runbook: Make the server an installable package

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else. If a step needs knowledge that is not written down
here or linked from here, the runbook is not finished.

**Story:** S01 | **Milestone:** M01 | **Date:** 2026-09-14

## 1. What this does

This project is a Model Context Protocol server. MCP is a standard way for an AI
client, such as Claude Desktop, to call tools that someone else has written. This
particular server answers questions about ships: which vessels are near a given
Malaysian port, which are tankers currently at anchor, and the full record for
one named ship. It holds a fixed dataset of 18 vessels, so it needs no network
access, no API key and no account.

Before this story, the server could only run from inside a copy of the source
code, and starting it meant writing two absolute filesystem paths into your AI
client's configuration. Get either wrong and the server would start successfully
and then fail the first time you asked it anything. After this story you install
it once and start it by typing its name. You can tell it is working because the
offline check in section 5 prints four lines about ships and ends with
`All smoke checks passed.`

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.10 or newer. Built and tested against 3.14.6 | `python3 --version` |
| pip | Any version that ships with the above. Tested with 26.1.2 | `python3 -m pip --version` |
| git | Any recent version. Only needed to obtain the code | `git --version` |

On macOS, `python3` exists by default but a bare `python` often does not. Every
command below uses `python3` outside a virtual environment and `python` inside
one, where it always exists. This is not a typo.

No external accounts, keys or services are needed.

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| none | This server reads a dataset bundled inside the package | not applicable |

## 3. First time setup

**Read this first.** As of 2026-09-14 this work lives on the branch
`chore/S01-installable-package`, which is pushed to GitHub but not merged.
`main` still carries the old layout with no `pyproject.toml`, so a plain clone
followed by `pip install .` will fail. You need the extra checkout line below
until the branch is merged.

```bash
git clone https://github.com/Ariefrse/maritime-mcp-server.git
cd maritime-mcp-server
git checkout chore/S01-installable-package
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Once the branch is merged into `main`, drop the `git checkout` line and the rest
works unchanged.

The last command should end with a line beginning `Successfully installed`,
listing `maritime-mcp-server-0.1.0` and about twenty five other packages it
depends on.

`source .venv/bin/activate` puts you inside the virtual environment. Your prompt
will usually gain a `(.venv)` prefix. If you close the terminal and come back
later, run that one command again from the project directory before anything
else. You do not need to repeat the install.

## 4. Run it

```bash
maritime-mcp-server
```

**What you should see:** nothing at all. The terminal will appear to hang.

That is correct and is the most confusing thing about this program. An MCP server
over stdio does not print a banner or a ready message. It waits silently for a
client to send it structured messages on standard input. A silent, hanging
terminal means success. Press Ctrl+C to stop it.

If it instead prints a red block of text ending in `ModuleNotFoundError` or
`command not found`, see section 6.

To actually use it, you point an AI client at it rather than running it by hand.
For Claude Desktop, edit
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS and
add:

```json
{
  "mcpServers": {
    "maritime-vessel-data": {
      "command": "/absolute/path/to/maritime-mcp-server/.venv/bin/maritime-mcp-server"
    }
  }
}
```

Replace `/absolute/path/to/` with the real location. Running `pwd` inside the
project directory prints it. Restart Claude Desktop fully, then ask it something
like "which tankers are at anchor near Port Klang". No `args` and no `cwd`
entries are needed; if you are copying an older config that has them, delete them.

## 5. Verify it works

Fast confidence check. The full set of cases is in `testscript.md` beside this
file.

```bash
source .venv/bin/activate
python -m maritime_mcp_server.smoke_test
```

**Expected output, exactly:**

```
search_vessels(Tanker, At anchor) -> 1 vessel(s): ['Seri Alam']
vessels_near_port(Port Klang, 30nm) -> 5 vessel(s), nearest Bunga Mas Lima at 0.1nm
vessel_details('Kowloon Express') -> MMSI 477055221, flag Hong Kong
vessel_details('999999999') -> No vessel found matching '999999999'.

All smoke checks passed.
```

Second check, the one this story exists for. This proves the server no longer
depends on where you run it from:

```bash
cd /
python -c "import json; from maritime_mcp_server.server import vessel_details; print(json.loads(vessel_details('Kowloon Express'))['mmsi'])"
```

**Expected:** `477055221`. Before this story, the same command from `/` produced
a file not found error.

Third check, for whether it genuinely speaks the protocol rather than merely
importing:

```bash
printf '%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
'{"jsonrpc":"2.0","method":"notifications/initialized"}' \
'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"vessel_details","arguments":{"query":"Kowloon Express"}}}' \
| maritime-mcp-server 2>/dev/null
```

**Expected:** two long lines of JSON. The first contains
`"name":"maritime-vessel-data"`. The second contains `477055221`. If you get only
one line, run it again; the server can shut down on end of input before handling
the last message, which is a quirk of feeding it this way rather than a fault.

## 6. When it goes wrong

Every row here is a failure that actually occurred while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, with a message about FastMCP being renamed to MCPServer | You have `mcp` 2.x installed. This code is written against 1.x. Most likely you installed `mcp` by hand rather than letting `pip install .` choose | `pip install --force-reinstall .` The project pins `mcp>=1.2.0,<2` and will pull the correct version. Confirm with `pip show mcp`, which should report 1.30.0 |
| `zsh: command not found: maritime-mcp-server` | The virtual environment is not active. The command only exists inside it | `source .venv/bin/activate` from the project directory, then try again |
| `zsh: command not found: python` | You are outside the virtual environment, where macOS provides only `python3` | Either activate the environment, or use `python3` for that command |
| Server starts, then the AI client reports an error the first time you ask about a ship | Your client config still has an old `cwd` or `args` entry pointing at a source checkout | Replace the whole `maritime-vessel-data` block with the three line version in section 4 |
| `FileNotFoundError` mentioning `data/vessels.json` | You are running an old copy from before this story, which located its dataset by walking up out of the package | Pull the latest code and reinstall with `pip install .` |
| `pip install .` fails complaining there is no `pyproject.toml` or `setup.py` | You are on a commit from before this story | `git checkout chore/S01-installable-package`, or whichever branch or tag carries this work |
| `git log --follow` on a moved file returns nothing | The rename is staged but not yet committed. `--follow` reads history, and staged changes are not history | Commit first, then re-run. `git show --stat -M <commit>` is the direct evidence |

## 7. Where things live

| What | Path |
|------|------|
| The server and its three tools | `maritime_mcp_server/server.py` |
| The vessel dataset, 18 records | `maritime_mcp_server/data/vessels.json` |
| Offline check | `maritime_mcp_server/smoke_test.py` |
| Package metadata, dependency pin, console script | `pyproject.toml` |
| User facing setup instructions | `README.md` |
| This story's plan, tests, retro and runbook | `.shipline/work/M01-harden-and-package/S01-installable-package/` |
| Project wide rules learned from retros | `.shipline/guardrails.yaml` |
| Verify command Shipline runs unattended | `.shipline/config.json`, under `verify.commands` |

## 8. Rolling back

This story is two commits on one branch. `main` was never touched, so rolling
back is cheap. The branch is pushed, so a full removal means deleting it on the
remote as well as locally.

To leave the work alone and simply return to the previous state:

```bash
cd maritime-mcp-server
git checkout main
```

`main` still has the original `src/` layout and the old `README.md`. Note that
the old layout has the dependency problem described in section 6 row one, so a
fresh install from `main` will not work without pinning `mcp<2` by hand.

To undo the commit but keep the changes as uncommitted edits, so you can adjust
and recommit:

```bash
git checkout chore/S01-installable-package
git reset --soft HEAD~1
```

To destroy the work entirely:

```bash
git checkout main
git branch -D chore/S01-installable-package
git push origin --delete chore/S01-installable-package
```

To also remove the installed command from your environment:

```bash
source .venv/bin/activate
pip uninstall maritime-mcp-server
```

Or simply delete the whole `.venv` directory, which is not tracked by git.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **Section 3 was verified against a clone of the local repository, not against
  GitHub.** The clone, checkout, venv and `pip install .` sequence succeeded:
  exit 0, with `maritime-mcp-server` on PATH. The branch has since been pushed,
  so the same sequence against the GitHub URL should behave identically, but it
  was not re-run from there. The `git checkout` line is required until the branch
  is merged into `main`.
- **The Claude Desktop configuration in section 4 was not tested in Claude
  Desktop.** The server was verified to answer a real MCP handshake driven from
  a terminal, which exercises the same protocol, but no AI client was actually
  pointed at it. The JSON shape follows the documented format and drops the
  `args` and `cwd` keys that are no longer required.
- **The rollback commands in section 8 were not executed**, since executing them
  would have destroyed the story. They are standard git operations and the branch
  and commit they name are real, but they were written rather than run.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon. Nothing in the project is platform specific, and the wheel is marked
  `py3-none-any`, but Linux and Windows are untried. The `~/Library/Application
  Support/` path in section 4 is macOS only.
- **Python 3.10, 3.11, 3.12 and 3.13 are untested.** `requires-python` declares
  3.10 or newer, and the only API in question, `importlib.resources.files`, has
  been available since 3.9. But every command in this runbook was run on 3.14.6.
