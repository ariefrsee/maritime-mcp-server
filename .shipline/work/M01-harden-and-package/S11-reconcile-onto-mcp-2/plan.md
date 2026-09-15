---
pipeline_state:
  story_id: S11
  milestone: M01
  title: Reconcile the two lines onto mcp 2.x
  current_phase: build      # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan]
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
