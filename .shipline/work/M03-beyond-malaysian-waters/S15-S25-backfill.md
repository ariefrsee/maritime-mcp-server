---
pipeline_state:
  story_id: S15-S25
  milestone: M03
  title: What shipped between S15 and S25, recorded after the fact
  current_phase: done
  phases_completed: [deliver]
  approved_by_user: true
  started_at: 2026-09-15
  last_updated: 2026-09-18
---

# S15 to S25: recorded after the fact

## Why this file exists and what it is not

Eleven stories shipped without a story folder. This is the record of that,
written on 2026-09-18 by reading `git log`, not a set of plans.

It is deliberately one file rather than eleven `plan.md` files. A plan written
after the work claims to have guided the work, and these did not exist while any
of it was being built. Backfilling them would make the pipeline look followed
when it was not, which is a worse outcome than an honest gap: the value of the
record is that it can be trusted, and a fabricated plan spends exactly that.

What was maintained throughout: the guardrails. G25 to G30 were each written
when the mistake that earned them happened, and they are in `guardrails.yaml`
with the story that discovered them. The tests and the commit messages are also
contemporaneous. It is the planning artefacts, and only those, that are missing.

## What shipped

| Story | Merged | What it did |
|-------|--------|-------------|
| S15 | 2026-09-15 | `vessels_watched`, so deselecting a region stops showing its vessels. The store keeps a deselected region for 30 minutes, which is right for the store and wrong for the caller. |
| S16 | 2026-09-17 | The Malacca Strait as a region of its own. |
| S17 | 2026-09-17 | Class B identity, from messages 19 and 24, which this server had been discarding. Port calls reconstructed from the recorded track. |
| S18 | 2026-09-17 | Cleared the "Unknown type 0" labels an earlier version had written into the identity table. |
| S19 | 2026-09-17 | Hourly congestion, and the removal of a class of test that was really a countdown to a future failure. |
| S20 | 2026-09-17 | Traffic density as a grid of cells. |
| S21 | 2026-09-17 | Anchorages found by clustering recorded positions rather than read off a chart. |
| S22 | 2026-09-17 | Report the anchorage itself, not the bounding box around it. The box was 226 nm2 against 64 nm2 actually occupied. |
| S23 | 2026-09-18 | Observed passage times, and the flag that was already derivable from the MMSI. |
| S24 | 2026-09-18 | Fixed the port table name, which was written from memory and existed under another name, and added Singapore to it. |
| S25 | 2026-09-18 | The particulars AIS was already sending and this server dropped: draught, IMO, call sign, declared arrival, beam, rate of turn, position accuracy. |

## Which of these belong to M03

S15 and S16 do: both are about which water is being watched, which is this
milestone's subject.

S17 to S25 do not. They continued the story numbering because numbering runs
across milestones in this project, but their subject is the depth of what is
known about a vessel, not the breadth of the sea area. They were built without a
milestone being opened for them. Naming that here is the point of this section:
the milestone boundaries stopped describing the work somewhere around S17, and
the next milestone should be opened deliberately rather than inherited.

## Open from M03

G4 of the master plan is still open: eleven of the nineteen regions carry no
measured message rate. They report unknown rather than zero, which is the
behaviour G3 asked for, but they are unmeasured because the sweep that would
measure them was throttled by the feed provider partway through.
