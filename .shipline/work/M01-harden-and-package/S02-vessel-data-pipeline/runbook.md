# S02 Runbook: Vessel data pipeline, offline half

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S02 | **Milestone:** M01 | **Date:** 2026-09-14

## 1. What this does

This server answers questions about ships for an AI assistant. Until this story
it had exactly one source of information: a file containing 18 made up vessels
that never move.

This story does not connect it to real ships. It builds the parts that will let
it, and it makes the server honest in the meantime.

Three things changed that you can actually observe:

- **Every answer now says where it came from.** A `data` block at the top of each
  response reads `"source": "snapshot"` and carries a note saying the positions
  are not current. Once live data is connected it will read `"source": "live"`.
  You can no longer be shown a made up position as though it were real.
- **The server can now understand real AIS messages.** Ships broadcast their
  identity over the air in a compact numeric format. The server translates that
  into the same record shape it already used.
- **It refuses to guess.** Real ships broadcast their position far more often
  than their name or size. When something is unknown, the answer says `null`
  rather than filling in a plausible value.

You can tell it is working because section 5's replay command turns 199 real
captured messages into 89 correctly described vessels.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.10 or newer. Built and tested against 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |

**No network connection is needed** for anything in this runbook, and **no API
key**. That was the point of splitting this story from the live half.

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| none | not used by this story | S03 introduces `AISSTREAM_API_KEY` |

## 3. First time setup

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

This is on `main` as of 2026-09-14, so a plain clone is all you need.

## 4. Run it

```bash
maritime-mcp-server
```

**What you should see:** nothing. The terminal appears to hang.

That is correct. This kind of server prints no banner and waits silently for an
AI client to talk to it over standard input. A silent, hanging terminal means it
started. Press Ctrl+C to stop.

To see it actually answer something, use section 5 instead.

## 5. Verify it works

**The fast check:**

```bash
source .venv/bin/activate
python -m maritime_mcp_server.smoke_test
```

Expected, exactly:

```
search_vessels(Tanker, At anchor) -> [snapshot] 1 vessel(s): ['Seri Alam']
vessels_near_port(Port Klang, 30nm) -> [snapshot] 5 vessel(s), nearest Bunga Mas Lima at 0.1nm
vessel_details('Kowloon Express') -> MMSI 477055221, flag Hong Kong
vessel_details('999999999') -> No vessel found matching '999999999'.
vessels://all -> [snapshot] 18 vessel(s)

All smoke checks passed.
```

The `[snapshot]` tags are the point. They say this is sample data.

**The check that proves this story did something.** This replays 199 real AIS
messages, captured from ships in the Strait of Malacca on 2026-09-14, through
the new translation layer. No network, no key:

```bash
python tools/replay_sample.py
```

Expected: 199 messages in, 198 accepted, 1 rejected. Then `89 vessels, 3 not a
ship, 8 no position`. Then a coverage table, then two example vessels.

**Read the two examples at the end.** The first has full details because that
ship broadcast its identity. The second shows `"type": null` and
`"length_m": null`, because that ship has only broadcast its position so far.
That is the refusal to guess, working.

The full set of twelve cases is in `testscript.md` beside this file.

## 6. When it goes wrong

Every row is a failure that actually occurred while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `TypeError: string indices must be integers, not 'str'` | You have code written against the old output shape. Tools used to return a bare list and now return `{"data": ..., "vessels": [...]}` | Read `response["vessels"]` instead of iterating the response directly. This was a deliberate change to carry provenance |
| A vessel you can see in the data is "not found" by `vessel_details` | Older behaviour required a known position. A ship that broadcast its name but not yet its location was invisible | Fixed in this story. If you see it again, the store is being queried with `require_position=True` |
| Every vessel disappears from the store immediately | Ageing was computed from the wrong field. The `Timestamp` inside an AIS message is the second of the minute, not a clock | Use `MetaData.time_utc`. It is in Go's format, not ISO 8601, so `datetime.fromisoformat` will not parse it |
| A buoy or lighthouse appears in the vessel list | Not everything broadcasting AIS is a ship. Aids to navigation use MMSIs beginning `99` | `mmsi_kind()` classifies these and the store excludes them. Flag coverage went from 90/92 to 89/89 when this was fixed |
| A vessel has no flag | The flag is not transmitted by AIS at all. It is derived from the MMSI's country digits | Expected for malformed identifiers. If a real ship lacks one, its three digit prefix is missing from `data/mid_countries.json` |
| `Destination` looks like nonsense, e.g. `OMSLL>SGSIN` | It is free text typed by crew. Real values include `SGSIN`, `SG SIN`, `KEPPEL K 15` | Working as intended. It is passed through trimmed and never "cleaned", because normalising it would invent information |
| `zsh: command not found: python` | You are outside the virtual environment | `source .venv/bin/activate`, or use `python3` |

## 7. Where things live

| What | Path |
|------|------|
| The three tools and the resource | `maritime_mcp_server/server.py` |
| Source seam and provenance, `get_vessels()` | `maritime_mcp_server/server.py` |
| AIS translation, lookup tables, MMSI classification | `maritime_mcp_server/ais_mapping.py` |
| Country codes for flag derivation, 292 entries | `maritime_mcp_server/data/mid_countries.json` |
| Vessel store, merging and expiry | `maritime_mcp_server/store.py` |
| Bundled 18 vessel fallback | `maritime_mcp_server/data/vessels.json` |
| Real captured AIS messages, the test fixture | `tests/data/ais_capture.json` |
| Replay tool | `tools/replay_sample.py` |
| This story's plan, tests, retro and runbook | `.shipline/work/M01-harden-and-package/S02-vessel-data-pipeline/` |
| Project rules learned from retros, now 10 | `.shipline/guardrails.yaml` |

## 8. Rolling back

This story is one commit, merged into `main` as `eab8d83` and pushed. Rolling
back means reverting a merge on a published branch.

To inspect the previous state without changing anything:

```bash
git checkout 4f3291e
```

That is S01 as merged, before any of this. Return with `git checkout main`.

`main` still works fully. It has the original bare list output shape and the 18
vessel snapshot, with no provenance block.

To undo the merge on `main` and publish the undo:

```bash
git checkout main
git revert -m 1 eab8d83
git push origin main
```

`-m 1` keeps the state of `main` before the story. This adds a new commit rather
than rewriting history, which is the safe option on a published branch.

**One thing rolling back does not undo.** If you have already pointed an AI
client at this version and written anything that reads the `data` block, going
back to `main` removes it and that code will break. Nothing outside this
repository consumes these tools today, so this is theoretical for now.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **Section 3 was verified against a clone of the local repository, not against
  the GitHub URL.** The install itself, from a clean wheel in a venv created
  outside the repository, was verified: `pip install .` exited 0 and the mapping
  resolved its data file from `site-packages`. The work is now merged and pushed,
  so the same sequence against GitHub should behave identically, but it was not
  re-run from there.
- **The rollback commands in section 8 were not executed**, because doing so
  would have destroyed the story. The branch and commit they name are real.
- **Section 4 was verified only to the point of the server starting and exiting
  cleanly.** No AI client was pointed at this version. S01's runbook has a
  terminal based protocol handshake that does exercise the wire, and it still
  applies, but it was not re-run against this story's output shape.
- **The live path does not exist yet and nothing here tests it.** `source` is
  always `snapshot`. The translation layer has been exercised against real
  captured messages, but never against a live connection. That is S03.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon. Python 3.10 through 3.13 are declared supported and untried.
- **The captured fixture is 375 seconds of one afternoon in one region.** Status
  codes, ship types and station types exist that it does not contain. Unknown
  values report themselves rather than failing, but they have not been seen.
