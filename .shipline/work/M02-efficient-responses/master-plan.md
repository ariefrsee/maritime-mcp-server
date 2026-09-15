---
pipeline_state:
  milestone: M02
  title: Efficient responses
  state: in_progress       # planning | in_progress | verification | done
  branch: milestone/M02
  started_at: 2026-09-15
  due_date: TBD
  last_updated: 2026-09-15
  stories_total: 1
  stories_done: 1
  stories_open: 0
---

# M02: Efficient responses

Milestone rollup. This sits above the individual story plans. Each story owns its
own folder with a plan, a test script, a retro and a runbook. This file tracks the
whole.

Status legend: done, in progress, planned, blocked.

## 1. Overview

| Field | Value |
|-------|-------|
| Milestone | M02 |
| Title | Efficient responses |
| State | In progress |
| Branch | `milestone/M02` |
| Started | 2026-09-15 |
| Due | TBD |

**Story numbering continues from M01 rather than restarting.** Guardrails record
the story they came from, so a second S01 would make `discovered_in` ambiguous.

## 2. Goals

What has to be true when this milestone closes. Each goal maps to at least one
story. A goal with no story behind it is a wish, not a goal.

- [x] G1: A typical question costs a fraction of what it costs today. Measured, not asserted: `vessels_near_port("Tanjung Pelepas", 40)` currently returns 26,713 characters, roughly 6,678 tokens, for 67 vessels.
- [x] G2: The size of a response is bounded by what was asked, not by how much traffic happens to be in the water.
- [x] G3: Nothing about the honesty of the data is traded for size. Provenance stays, derived fields stay marked, and an unknown value is never made to look like a known one.

## 3. Scope

### In scope

- How a response is written down: formatting, precision, redundancy.
- What a response contains by default, and how a caller asks for more.
- Bounding the number of records any one call can return.

### Out of scope

Deferred deliberately. Write the reason, not just the item.

- Splitting the collector from the server lifecycle. A larger change that fixes the cold start and enables history, and the right subject for its own milestone.
- Persisting state so the fallback is last known data rather than a bundled sample. Depends on the above.
- Continuous integration. Still the most valuable unstarted infrastructure work, and unrelated to response size.

## 4. Story rollup

| Story | Title | Status | Size | Priority | Branch | Plan |
|-------|-------|--------|------|----------|--------|------|
| S07 | Compact responses | Done | M | High | `feat/S07-compact-responses` | [plan](S07-compact-responses/plan.md) |

## 5. Open risks

| Risk | Impact | Mitigation | Owner |
|------|--------|------------|-------|
| Dropping null fields to save space weakens the promise S02 made, that an unknown value is explicitly null rather than absent | An absent field reads as "not sent" rather than "not known", which is a different claim | Raised at the gate as a decision for the user, not made in a build. If taken, the tool description must state that an absent field means AIS has not reported it | ariefrse |
| Optimising for token count encourages returning less than the question deserves | Answers get thinner rather than tighter | Every reduction must be justified as redundancy or precision, not as omission. G3 above is the check | ariefrse |
| The server has still never been used by a real client | The cost being optimised is measured from the terminal, not observed in a conversation | Named plainly. The measurements are real; whether they matter in practice is untested | ariefrse |

## 6. Closing checklist

- [ ] Every story is Done or explicitly moved out with a written reason
- [ ] Every goal in section 2 is ticked or explicitly dropped
- [ ] Every retro has been read and its guardrails are in `.shipline/guardrails.yaml`
- [ ] `config.json` milestone history updated
