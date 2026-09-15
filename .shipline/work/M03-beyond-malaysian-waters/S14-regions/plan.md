---
pipeline_state:
  story_id: S14
  milestone: M03
  title: Regions, within the budget the feed allows
  current_phase: retro     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify, test]
  approved_by_user: true
  branch: feat/S14-regions
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G6, G7, G8, G9, G11, G15, G16, G17, G18, G19, G20, G23, G24]
---

# S14: Regions, within the budget the feed allows

## 1. What this is

The ask was to view other countries, and all countries. The first is
straightforward. The second is not available on this account, and finding that
out before building was the most valuable part of the story.

## 2. Evidence

Per G2 and G7, measured rather than assumed. Each run a fresh connection,
2026-09-15, one account.

| Subscription | Rate | Outcome |
|---|---|---|
| Malaysia | 0.4/s | stable |
| Gulf of Thailand | 0.03/s | stable, one vessel in 76s |
| Vietnam | 0.03/s | stable, one vessel in 76s |
| Singapore Strait | 0.38/s | stable |
| Indonesia | 3.57/s | stable |
| East Asia | 3.8/s | stable for 151s |
| Southeast Asia | 8.0/s | stable for 181s, twice |
| US East Coast | 10.1/s | stable for 151s |
| Mediterranean | 25.1/s | stable for 152s |
| Europe | 72.2/s | dropped at 126s |
| World, two boxes | 72.3/s | dropped |
| World, one box | 78 to 122/s | dropped at 31s, 37s and 51s |

Three conclusions, each of which changed the design:

**The limit is throughput, not area and not box count.** Two boxes covering the
world died the same way one did. Several boxes in one subscription are fine
while their combined rate stays inside the budget.

**One connection per key, near enough.** With production holding one, four more
were opened and three were refused at the handshake. A connection per region
was the obvious alternative design and it is not available.

**An established connection is not affected by the throttle.** During a sweep
that had every new connection refused inside three seconds, production kept
running and its freshest fix stayed one second old. This is why set_regions
updates the open socket instead of reconnecting: reconnecting during a throttle
window would take the service down.

## 3. What was built

- `regions.py`: eighteen named areas, each carrying the rate it was measured
  at, the budget, and the evidence behind the budget.
- `Collector.set_regions`: re-subscribes on the open socket, paced to the
  vendor's one update per second.
- `list_regions`, `set_regions`, `vessels_in_area` MCP tools.
- `vessels://all` unchanged, so nothing that reads it breaks (G9).

## 4. Acceptance criteria

Each one fails if the behaviour is absent (G11), and each names the check
rather than a feeling (G18).

- **AC-1** An unconfigured server still watches Malaysian waters and nothing
  else. `test_the_default_subscription_is_still_malaysia`, and S09's coverage
  tests moved onto the region table rather than being deleted with the constant
  they were written against.
- **AC-2** A selection of measured regions reports the sum of their rates.
  `test_a_selection_of_measured_regions_sums_its_rates` asserts 3.97 for
  Malaysia plus Indonesia.
- **AC-3** A selection containing an unmeasured region reports an unknown total,
  not a partial sum. `test_a_selection_containing_an_unmeasured_region_has_an_unknown_total`.
- **AC-4** An unmeasured rate is null and not zero.
  `test_an_unmeasured_region_is_null_and_not_zero`.
- **AC-5** The same region key works padded, capitalised, spaced or underscored,
  through every entry point (G19). `test_a_region_key_is_normalised_the_same_way_everywhere`.
- **AC-6** An over budget selection is applied and flagged, not refused.
  `test_an_over_budget_selection_is_allowed_and_flagged`.
- **AC-7** The tools answer correctly over the real MCP protocol, not only when
  called directly (G20). Driven over stdio: all three present, bad bbox, unknown
  region and empty arguments each answered with a reason.

## 5. Mutation testing

Per G17, each invariant was broken on purpose and the named test watched to fail.

| Mutation | Test that failed |
|---|---|
| `rate_for` sums an unmeasured region as zero | `test_a_selection_containing_an_unmeasured_region_has_an_unknown_total` |
| `DEFAULT_REGIONS = ("indonesia",)` | `test_the_default_subscription_is_still_malaysia` and three others |
| `within_budget(chosen)` back to the inline `rate <= budget` | `test_set_regions_survives_a_selection_nobody_has_measured` |

## 6. Cost as well as saving (G24)

The server gained three tools. Their schemas add roughly 1.4 KB to the tool list
every client loads once per session. `vessels://all` is unchanged, so no
existing response grew. `vessels_in_area` exists to make responses smaller when
a selection spans several regions, but nothing measures that yet because no
selection that large has been run.

## 7. Open

Eleven of eighteen regions are unmeasured. The sweep that measured five was
refused on every connection after that, and those runs recorded 0.00/s, which
is the throttle speaking rather than the water. They were discarded rather than
written down. Measuring the rest needs a session spaced out enough not to trip
the limit, and must not be run while production depends on reconnecting.
