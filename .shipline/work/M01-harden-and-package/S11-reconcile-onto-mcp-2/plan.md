---
pipeline_state:
  story_id: S11
  milestone: M01
  title: Reconcile the two lines onto mcp 2.x
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: feat/S11-reconcile-onto-mcp-2
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S11: Reconcile the two lines onto mcp 2.x

## 1. What this is

This repository has been developed twice in parallel and the two lines cannot
both be `main`.

The remote migrated to the mcp 2.x `MCPServer` API, added input validation and
made responses compact. This machine, starting from the same commit, added five
stories: AIS sentinels and port distance, durable history, course and heading,
all Malaysian waters, and fleet history. Neither side knew about the other.

The cause is worth writing down rather than glossing: nothing was pulled before
the local work began. Six commits existed on the remote and were never fetched.
Everything below is the cost of that.

## 2. Evidence

Per G2, all measured.

**The histories split at `9601feb`**, the README rewrite. Local `main` is ahead
10 and behind 6.

**Story numbers collide**, because both lines numbered from the same base:

| id | remote | local |
|---|---|---|
| S04 | migrate to the mcp 2.x MCPServer API | (none) |
| S06 | validate tool inputs | clear the AIS not-available sentinels |
| S07 | compact responses | vessel history that survives a restart |

**The overlap is small.** Files changed by both sides:

```
maritime_mcp_server/server.py
README.md
tests/test_server.py
```

Everything else built locally sits in files the remote never touched:
`history.py` (new), `store.py`, `ais_mapping.py`, `collector.py`,
`tests/test_history.py` (new), `tests/test_store.py`, `tests/test_ais_mapping.py`.

**The APIs are close.** `@mcp.tool()` is unchanged. The differences are the
constructor, `MCPServer("maritime-vessel-data", version=..., lifespan=...)`
against `FastMCP(...)`, the import path `mcp.server.mcpserver` against
`mcp.server.fastmcp`, `Annotated[..., Field(...)]` on parameters, and a
`_compact()` helper replacing `json.dumps(..., indent=2)`.

**Only one line can run here.** The venv holds mcp 1.30.0, and the remote main
does not import:

```
$ .venv/bin/python -c "import maritime_mcp_server.server"
ModuleNotFoundError: No module named 'mcp.server.mcpserver'
```

## 3. Direction

The remote wins on the SDK and the local line moves onto it.

The reason is G1. That guardrail exists because an unbounded `mcp>=1.2.0` pin
resolved to 2.x and broke the import, and the fix was to bound it. Staying on
1.x now would mean holding a `<2` ceiling against an SDK that has already moved,
which is the same debt in the other direction. The remote has already paid the
migration cost and it should not be paid twice.

## 4. Scope

In scope:

1. Rebase or replay the five local stories onto `origin/main`.
2. Re-express the two tools added locally, `vessel_track` and `fleet_track`, in
   the 2.x style: `Annotated` parameter validation, responses through
   `_compact()`.
3. Upgrade the venv to mcp 2.x and bound it at the next major.
4. Reconcile `README.md`, which both sides rewrote.
5. Renumber the colliding local stories so the milestone reads honestly.

Out of scope (F5):

- Any new behaviour. This story moves existing, tested work onto a different
  SDK and changes nothing a caller can observe, except where the remote's own
  compact and validation stories already changed it.
- Reviewing or altering the remote's three stories. They are merged and they
  stand.
- The dashboard, beyond confirming it still speaks to the reconciled server.

## 5. Contract decision (G9)

Callers see the union of both lines: validated inputs and compact responses from
the remote, plus `nearest_port_nm`, `course_degrees`, `heading_degrees`,
`vessel_track` and `fleet_track` from here.

One thing to watch rather than assume: the remote's compact-response story and
the local stories that added fields pull in opposite directions. The fields stay;
they are not optional. If the payload becomes a problem it is a later decision,
taken with a measurement, not quietly during a merge.

## 6. Acceptance criteria

1. `main` contains the remote's six commits and all five local stories, with no
   commit discarded from either side.
2. The venv runs mcp 2.x and `pyproject.toml` bounds it below 3 (G1).
3. `import maritime_mcp_server.server` succeeds.
4. Every test from both lines passes: the remote's and the local 213.
5. `vessel_track` and `fleet_track` carry `Annotated` validation like every
   other tool, and their bounds are tested.
6. Every tool response goes through `_compact()`, including the two added here.
7. `nearest_port_nm`, `course_degrees` and `heading_degrees` survive the move,
   asserted against the real captured fixtures.
8. A live run against aisstream returns vessels, a track and a fleet track.
9. The colliding story ids are renumbered and the milestone rollup reads
   correctly.
10. `smoke_test` ends with `All smoke checks passed.`

## 7. Risks

| Risk | Handling |
|---|---|
| A rebase silently drops a commit | Criterion 1 is checked by counting commits from both sides, not by the absence of conflicts |
| mcp 2.x changed behaviour beyond the rename | Criterion 4 runs both suites; anything that moves gets recorded rather than patched over |
| The dashboard breaks against the reconciled server | It is spawned from a checkout, so it is exercised live in criterion 8 before this is called done |
| Renumbering rewrites history others may hold | The remote branches are not rewritten; only local story directories and their frontmatter are renamed |

## 8. Verify

```
$ .venv/bin/python -m pytest
246 passed

$ .venv/bin/python -m maritime_mcp_server.smoke_test
All smoke checks passed.
```

Both suites together: 213 local plus the remote's, none skipped, none deleted.

Live, through a real MCP client on mcp 2.2.0:

```
  tools: search_vessels, vessels_near_port, vessel_details, vessel_track, fleet_track
  vessels://all -> live, 240 vessels
    DENITA WAVE  port Port Dickson 4.6 nm  course 233.0  heading 139.0
  vessel_track -> 2 positions
  fleet_track  -> 414 vessels, 4520 positions, truncated False
  fleet_track(hours=-5) -> rejected by validation
```

That last line is the point of the story in one output: a tool added on the
local line, rejecting a bad argument through validation added on the remote
line, returning fields added by two more local stories.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | No commit discarded from either side | yes | `origin/main` is an ancestor of HEAD, and all five local story branches are reachable |
| 2 | mcp 2.x installed and bounded below 3 | yes | mcp 2.2.0, `pyproject` reads `mcp>=2,<3` |
| 3 | The server imports | yes | tools listed over stdio |
| 4 | Every test from both lines passes | yes | 246 passed |
| 5 | The two added tools are validated | yes | `fleet_track(hours=-5)` rejected |
| 6 | Responses go through `_respond` | yes | no `json.dumps` left in either added tool |
| 7 | Local fields survive | yes | `nearest_port_nm` 4.6, `course_degrees` 233.0, `heading_degrees` 139.0 |
| 8 | A live run returns vessels, a track and a fleet track | yes | above |
| 9 | Colliding ids renumbered | yes | S06 to S12, S07 to S13, every id now unique |
| 10 | smoke test passes | yes | above |

### What the conflict actually was

One file, `server.py`, one hunk. Their serialisation helpers against my
`_nearest_port` returning a distance. Both were kept. `README.md` and
`tests/test_server.py` merged without help, and every other file built locally
was untouched by the remote.

### Two budgets raised, deliberately

`test_a_typical_response_is_not_dominated_by_formatting` and
`test_the_default_limit_keeps_a_busy_answer_small` failed, which was the G9
tension in the plan arriving on schedule. The compact responses story set
15,000 and 6,000 before `nearest_port_nm`, `course_degrees` and
`heading_degrees` existed; those cost about 60 characters a vessel and took the
same calls to 18,116 and 6,771. The budgets moved to 20,000 and 7,500 with the
measurement written beside them. The fields were not dropped to fit.

### Numbering

Story numbers run across milestones here, so both collisions were real. Local
S06 became S12 and local S07 became S13. Branches and commit messages keep their
original names: rewriting published history to tidy a number costs more than the
number is worth, and each renamed plan says what it was called before.

### Follow-up, not built here (F5)

`.shipline/config.json` marks M01 done and M02 active, but six stories landed in
M01 after it was closed, because the local line did not know M01 had been
closed. Which milestone they belong to is the user's call, not a merge decision.
