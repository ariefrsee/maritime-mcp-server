---
pipeline_state:
  milestone: M03
  title: Beyond Malaysian waters
  state: in_progress       # planning | in_progress | verification | done
  branch: milestone/M03
  started_at: 2026-09-15
  due_date: TBD
  last_updated: 2026-09-15
  stories_total: 1
  stories_done: 1
  stories_open: 0
---

# M03: Beyond Malaysian waters

Milestone rollup. Story numbering continues from M02 rather than restarting.

## 1. Overview

| Field | Value |
|-------|-------|
| Milestone | M03 |
| Title | Beyond Malaysian waters |
| State | In progress |
| Branch | `milestone/M03` |
| Started | 2026-09-15 |

## 2. Goals

- [x] G1: The sea area being watched is a choice at runtime, not a constant in
      the source, and Malaysian waters remain what an unconfigured server watches.
- [x] G2: The cost of a choice is visible before it is made. A caller can see
      what a selection will cost and whether the feed will sustain it.
- [x] G3: A cost nobody has measured is reported as unknown, never as zero and
      never as a partial sum that happens to look affordable.
- [ ] G4: The eleven unmeasured regions carry real numbers.

## 3. Scope

### In scope

- Naming sea areas and their bounding boxes.
- Changing the live subscription without interrupting the feed.
- Filtering collected vessels to one area.

### Out of scope

- Watching the whole world at once. Measured as unavailable on this account:
  a global subscription is cut inside a minute, every time. It is an aisstream
  plan question rather than a code question.
- A connection per region. Also measured as unavailable: with production
  holding one connection, four more were opened and three were refused at the
  handshake.
- Shortening history retention. Was going to follow from global collection and
  no longer does, because global collection is not happening. At Malaysia's
  0.4 messages a second the ninety day record costs roughly 560 MB, so it stays.
