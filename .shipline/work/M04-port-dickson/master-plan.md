---
pipeline_state:
  milestone: M04
  title: Port Dickson for the agency desk
  state: in_progress       # planning | in_progress | verification | done
  branch: null
  started_at: 2026-10-15
  due_date: TBD
  last_updated: 2026-10-15
  stories_total: 1
  stories_done: 0
  stories_open: 1
---

# M04: Port Dickson for the agency desk

Milestone rollup. This sits above the individual story plans. Each story owns its
own folder with a plan, a test script and a retro. This file tracks the whole.

Status legend: done, in progress, planned, blocked.

The first Malaysian users this server serves directly are DonMaritime and
Arangmas Shipping & Forwarding, a 24/7 port agent at Port Dickson. The design,
with the measurements behind it, is in the dashboard repository:
`oceantrack-dashboard/docs/superpowers/specs/2026-10-15-port-dickson-board-design.md`.

Stories run on their own `feat/S<NN>-...` branches and merge to `main`, as S14
to S25 did. There is no milestone branch.

## 1. Overview

| Field | Value |
|-------|-------|
| Milestone | M04 |
| Title | Port Dickson for the agency desk |
| State | In progress |
| Branch | none, story branches merge to `main` |
| Started | 2026-10-15 |
| Due | TBD |

## 2. Goals

- [ ] G1: A caller can ask which ships are at Port Dickson now, which are
      heading there and which left in the last 48 hours, from recorded history,
      with times given as the windows the coverage actually supports.
- [ ] G2: Harbour craft that live in the port are kept apart from port calls.

## 3. Scope

### In scope

- One port, Port Dickson, defined as data so a second port is one entry.
- A port board tool over the history database.

### Out of scope

- Alerts for a watchlist of the agency's own ships. Needs a login and client
  names, which this public service does not hold.
- A Kuala Linggi board. The transfer area 13 to 18 nm south east is a separate
  port; it becomes one more entry once Port Dickson has proved the rules.
- Switching the `anchorages` tool from reported status to speed. Every stopped
  vessel at Port Dickson reports `Under way using engine`, so that tool finds
  nothing there, but changing it alters an existing tool's output (G9).
- Retuning `port_calls`. Its 60 minute gap rule fragments Port Dickson calls,
  where the median reporting gap is 47 minutes. Same G9 reason.

## 4. Story rollup

| Story | Title | Status | Size | Priority | Branch | Plan |
|-------|-------|--------|------|----------|--------|------|
| S26 | Port Dickson board | In progress | M | High | `feat/S26-port-dickson-board` | [plan](S26-port-dickson-board/plan.md) |

## 5. Open risks

| Risk | Impact | Mitigation | Owner |
|------|--------|------------|-------|
| Coverage at Port Dickson is roughly one fix an hour per stopped ship | Times are windows; a quiet day looks like an empty port | Every row carries last heard; silence is never reported as departure | S26 |

## 6. Closing checklist

- [ ] Every story is Done or explicitly moved out with a written reason
- [ ] Every goal in section 2 is ticked or explicitly dropped
- [ ] Every retro has been read and its guardrails are in `.shipline/guardrails.yaml`
- [ ] `config.json` milestone history updated
