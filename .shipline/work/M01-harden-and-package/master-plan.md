---
pipeline_state:
  milestone: M01
  title: Harden and package
  state: in_progress       # planning | in_progress | verification | done
  branch: milestone/M01
  started_at: 2026-09-14
  due_date: TBD
  last_updated: 2026-09-14
  stories_total: 1
  stories_done: 1
  stories_open: 0
---

# M01: Harden and package

Milestone rollup. This sits above the individual story plans. Each story owns its
own folder with a plan, a test script and a retro. This file tracks the whole.

Status legend: done, in progress, planned, blocked.

## 1. Overview

| Field | Value |
|-------|-------|
| Milestone | M01 |
| Title | Harden and package |
| State | In progress |
| Branch | `milestone/M01` |
| Started | 2026-09-14 |
| Due | TBD |

## 2. Goals

What has to be true when this milestone closes. Each goal maps to at least one
story. A goal with no story behind it is a wish, not a goal.

- [x] G1: The server is an installable Python package with a declared dependency set and a pinned Python version, not a loose `src/` folder plus a one line requirements file.
- [ ] G2: Every tool has real tests that assert behaviour, not just that the call returns without raising. The smoke test stays as the fast offline check.
- [ ] G3: Every tool validates its inputs and returns a clear, structured error for bad input instead of raising or returning something misleading.

## 3. Scope

### In scope

- Packaging metadata so the server can be installed and launched without a hand written absolute path in the client config.
- A test suite covering `search_vessels`, `vessels_near_port` and `vessel_details`, including their edge cases.
- Input validation and error handling across the three tools and the `vessels://all` resource.

### Out of scope

Deferred deliberately. Write the reason, not just the item.

- Live AIS data. It depends on an external feed and credentials, and swapping the data source is a cleaner change once the tool surface is covered by tests. This is the natural M02.
- HTTP and SSE transport plus authentication. Remote access is a different threat model and should not ride along with a packaging pass.
- New tools such as route ETA and anchorage occupancy. Adding surface area before the existing surface is tested makes both harder.

## 4. Story rollup

| Story | Title | Status | Size | Priority | Branch | Plan |
|-------|-------|--------|------|----------|--------|------|
| S01 | Make the server an installable package | Done | M | High | `chore/S01-installable-package` | [plan](S01-installable-package/plan.md) |

## 5. Open risks

| Risk | Impact | Mitigation | Owner |
|------|--------|------------|-------|
| Packaging changes break the documented Claude Desktop launch command in the README | Users following the README get a server that will not start | Update the README in the same story that changes the entry point, and verify the documented command by hand | ariefrse |
| `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` in the shell override repo git config silently | Commits land under an unintended identity | `commit_identity` is recorded in config.json. Verify authorship after every commit, not before | ariefrse |
| The `mcp<2` pin is a holding position. The code is written against a superseded major version | The gap widens over time and the eventual migration gets harder | Raised in S01 retro carry forward. Strongest candidate for the next story | ariefrse |

## 6. Closing checklist

- [ ] Every story is Done or explicitly moved out with a written reason
- [ ] Every goal in section 2 is ticked or explicitly dropped
- [ ] Every retro has been read and its guardrails are in `.shipline/guardrails.yaml`
- [ ] `config.json` milestone history updated
