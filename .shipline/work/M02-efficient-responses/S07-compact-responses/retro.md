# Retro S07: Compact responses

**Date:** 2026-09-15
**Project:** maritime-mcp-server
**Milestone:** M02
**Branch:** `feat/S07-compact-responses`

## 1. Journey

I suggested this story as an API redesign: return a summary, let the client ask
for detail, add a fourth tool. Measuring first showed that was the wrong story.
The expensive part was never what the tools returned, it was how it was written
down. Twenty-nine percent of a typical response was indentation.

So the plan dropped the summary tool before it was written, and the story became
a much duller one: serialise compactly, stop printing sixteen significant figures
for a measurement accurate to four, stop repeating the port name the caller just
gave you, and cap the list. That got 81% at the default and 50% like for like,
without adding a single tool.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Measured where the characters actually went before writing anything | My original suggestion was the wrong fix and was dropped |
| Build | One serialisation helper, one rounding table, a `limit` on two tools | The tool schema grew, which the headline number hides |
| Verify | Twelve criteria, all measured against a before capture | A test that guards an error bound is not a test that detects a feature |
| Test | Ten cases, three isolated reversions | Every number comes from one fixture |

## 2. Technical findings

### 2.1 The costly part was the formatting, not the content

**What happened:** `vessels_near_port("Tanjung Pelepas", 40)` returned 26,713
characters. Breaking that down by field before changing anything:

```
pure indentation          7,683 chars   29%
null fields               172 of 871    19% of fields
nearest_port              2,345 chars    8%   identical on every vessel
position_age_seconds      2,077 chars    7%   already summarised in provenance
lat + lon                 3,412 chars   12%   at full float precision
```

**Why it matters:** none of that is information. `indent=2` exists so a person
can read a file, and no person reads this. A coordinate like
`1.2196916666666666` prints sixteen significant figures for a measurement that is
not accurate to four.

**Fix:** compact separators, a rounding table applied at the edge, and dropping
two fields where the caller already has the value. 50% like for like, before the
`limit` does anything.

### 2.2 A cap is only safe if it announces itself

**What happened:** capping at 25 turns a 67 vessel answer into a 25 vessel
answer. Done naively, the caller is told "25 vessels near Tanjung Pelepas", which
is false.

**Fix:** `matches` and `returned` are separate fields, and the docstring says
that when they differ the list was capped and how to see the rest. For
`vessels_near_port` the nearest are kept, which is asserted rather than assumed:
the capped MMSIs must equal the head of the uncapped list.

**Why the shape matters:** this is the same failure S06 fixed, where a stray
space produced a confident wrong answer. A silent cap is that failure with better
performance numbers.

### 2.3 The headline number hid a cost

**What happened:** total captured bytes fell 20%, but `tools/list` **grew 29%**,
from 3,344 to 4,301 characters, because two tools gained a `limit` parameter with
a real description.

**Why it is still right:** the schema is sent once per session and the savings
land on every call. The break even is inside the first call:

```
 1 call :  30,057 ->  9,388
10 calls: 270,474 -> 55,171
```

**Why it is worth recording:** the first instinct was to quote the 81% and move
on. A per call saving and a per session cost are different units, and quoting
only the flattering one is how optimisation work becomes marketing.

### 2.4 Two tests, one name each, different jobs

**What happened:** during the G17 reversions,
`test_rounding_moves_a_vessel_by_less_than_fifteen_metres` **passed** with
rounding removed. Correctly: it bounds the error introduced by rounding, and no
rounding means no error.

**Why it matters:** read quickly, that test looks like it guards the rounding.
It does not. `test_coordinates_are_rounded_to_about_eleven_metres` does. Without
performing the reversion, I would have believed the wrong thing about my own
suite, which is exactly what G17 exists to prevent.

## 3. What went wrong

- **My original suggestion was the wrong fix, and I suggested it before
  measuring.** A summary tool with a detail lookup would have added surface area
  to solve a problem that was mostly whitespace. G20 says probe the running
  system before planning; it took writing the plan to remember that applies to my
  own architectural opinions too.
- **The null decision was put to the gate and came back unanswered.** "ok go" was
  approval to proceed, not an answer. I took the conservative option and said so,
  which is defensible, but a decision affecting every response was effectively
  made by me.
- **The tool schema growth was nearly unreported.** It was found while reading
  the per response table, not because anything required looking.
- **Every number comes from one 89 vessel fixture.** A live store has more
  vessels with more static data filled in. The percentages will differ and no
  live measurement was taken, even though a key was available.
- **The default limit of 25 was chosen by feel.** It is a real product decision,
  it silently shapes every answer, and nothing justifies 25 over 10 or 50.

## 4. What went right

- **Measuring by field before planning.** It killed a worse story and produced a
  better one. The whole plan changed on the strength of a ten line script.
- **Three isolated reversions rather than one.** Each failure named one cause,
  and one of them taught me something about my own tests that a combined revert
  would have hidden.
- **Keeping the nulls.** The 10% was available and declining it preserved a
  distinction S02 was careful about. Cheap to take, and it would have been the
  first place this project traded honesty for a number.
- **Asserting truncation keeps the nearest**, rather than assuming slicing a
  sorted list does the obvious thing.
- **Accounting for the schema growth in the test script**, so the story's own
  record does not read better than the change deserves.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G23 | Measure where the cost is before designing a fix for it | high | backend, frontend, mobile, infrastructure |
| G24 | Report the cost an optimisation adds, in the same units as the saving | medium | backend, frontend, mobile, infrastructure, ops |

Considered and rejected as guardrails:

- "Never silently truncate." Genuinely important and already covered by G8, never
  present data the source did not supply, and by S06's whole subject. A third
  rule saying the same thing would dilute both.
- "Get an answer to a gate question before proceeding." The gate worked; the user
  chose to delegate. A rule telling me to block on every unanswered question
  would make the pipeline worse, not better.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **The default limit of 25 is unjustified.** It shapes every answer and was
  picked by feel. Worth revisiting once anyone has used this in a real
  conversation.
- **No live measurement was taken.** A key was available and the sizes were only
  ever measured against the fixture. One live capture would cost minutes.
- **Milestone goals G2 and G3 are met; G1 needs a judgement.** "A fraction of
  what it costs today" is satisfied by 81% at the default, but the milestone
  should say what fraction was enough.
- **Still no CI.** 173 tests, under a second, no key, no network. Unchanged from
  four retros ago and still the most valuable unstarted work.
- **The larger design fixes are untouched**, deliberately: splitting the
  collector from the server lifecycle, and persisting state so the fallback is
  last known data rather than a bundled sample.
- **The server has still never been used by a real client.** Every number in this
  story is a terminal measurement. Whether 6,700 tokens was actually hurting
  anything is unobserved.
- **The API key is in the session transcript**, and a Context7 key sits in
  plaintext in `~/.zshrc`.
