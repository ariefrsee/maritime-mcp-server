# Retro S04: Migrate to the mcp 2.x MCPServer API

**Date:** 2026-09-15
**Project:** maritime-mcp-server
**Milestone:** M01
**Branch:** `feat/S04-migrate-to-mcp-2`

## 1. Journey

This story was planned a day ago, before S02, S03, S05 and S06 existed, and was
deliberately left until last. Re-reading it was the point: the plan claimed two
lines, and four stories had since added a lifespan hook, schema constraints and a
source seam that the claim had never been tested against.

The re-read was not a read. The whole migration was performed in a scratch copy
and the full 157 test suite run against it, which was impossible when the plan was
written because no tests existed. That found the one thing the plan had missed,
before the story was even approved.

The migration itself was two lines, as promised. Everything else in this story was
evidence gathering.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Revalidated by executing it, not reading it. Maturity raised 8 to 9 | `Tool.inputSchema` renamed. Found before approval |
| Build | Two import lines, a dependency range, a version fallback, two test lines | Nothing unexpected |
| Verify | Eleven criteria, wire captures diffed field by field | One criterion could not be tested as written |
| Test | Nine cases, mostly before-and-after comparisons | The live path can only be checked by hand |

## 2. Technical findings

### 2.1 A renamed attribute that no client can see

**What happened:** `Tool.inputSchema` became `Tool.input_schema` in 2.x. Two
tests failed:

```
AttributeError: 'Tool' object has no attribute 'inputSchema'.
                Did you mean: 'input_schema'?
```

**The part that matters:** the JSON is unchanged. A side by side capture shows
`inputSchema` on the wire under both versions, with identical constraints. So the
rename touches Python code reading tool metadata and nothing else.

**Why this is the clearest return S05 has produced:** without a test suite this
would have shipped silently. Nothing in the server reads that attribute, so the
smoke test would have passed, the wire comparison would have passed, and the
breakage would have surfaced later in whatever tooling reads tool definitions.
The tests found it in half a second, and they were written for entirely different
reasons.

### 2.2 A criterion that could not bite

**What happened:** AC-8 said installing `mcp>=3` should be reported as a
conflict. There is no `mcp` 3.x, so pip says `No matching distribution found`,
which says nothing about our bound.

**What was done instead:** temporarily declared `mcp>=2,<2.2` with 2.2.0
installed. Pip downgraded to 2.1.1. That is direct evidence the ceiling is
enforced rather than advisory.

**The accidental benefit:** the environment was then on 2.1.1, so the suite was
run there as well. It passes on both ends of the declared range. Declaring
`>=2,<3` is a claim about that whole range, and until this nothing had tested
more than the newest release. That should probably have been in the plan.

### 2.3 The version field was wrong before and is right now

**What happened:** under 1.x, `serverInfo.version` reported `1.30.0`, the SDK's
version. Under 2.x it defaults to an empty string.

**Why the old value was a bug:** a client asking what version of this server it
is talking to was told what version of the SDK it was built with. Two unrelated
numbers.

**Fix:** report the package's own version via `importlib.metadata`, with a
fallback. The fallback is not theoretical: `PackageNotFoundError` was reproduced
by running from a source checkout, which is exactly what happens when someone
clones and runs without installing.

### 2.4 The comparison tool finally got built

`tools/compare_wire.py` was specified in this plan a day ago and carried forward
unbuilt through three retros. S02 verified its seam by calling functions
directly; S03 wrote a throwaway client and deleted it. This story needed it and
so it exists, and it is what turned "the migration looks fine" into "exactly one
field differs across eleven responses".

It is worth noting how it got built: not because a retro said so three times, but
because a story could not be verified without it.

## 3. What went wrong

- **The plan said two lines, and two lines was right for the server but wrong for
  the story.** Two test lines also changed. A small gap, but "two lines" was the
  phrase that made this feel safe enough to leave until last, and it was stated
  before anything could test it.
- **AC-8 was written against a version that does not exist.** Writing a criterion
  whose failure condition cannot be produced is a way of guaranteeing it passes.
  G5 says a criterion must be evaluable at the phase that checks it; this one was
  evaluable in principle and untestable in practice, which G5 does not cover.
- **Nothing tested the range.** `>=2,<3` claims the code works across every 2.x
  release. Until an unrelated accident put the environment on 2.1.1, only the
  newest had been tried. No guardrail caught that.
- **The live path is still verified by hand.** `_session` is stubbed in every
  test, so AC-10 needed the user's key and a person reading output. That has been
  true since S03 and is still true.
- **The wire comparison only covers snapshot mode.** Live data changes between
  captures so it cannot be diffed. A 2.x behaviour difference that appears only
  under live data would not have been caught.

## 4. What went right

- **Revalidating by executing rather than reading.** The plan was a day old and
  looked fine. Running it found the only real breakage in the story before
  approval, which meant the gate presented a tested plan rather than a hopeful one.
- **Keeping this story last.** Written first, deferred four times, and every
  deferral made it safer: the test suite, the schema constraints and the source
  seam all arrived in between, and all had to survive the migration. Doing it on
  day one would have been a blind two line change.
- **Testing the mechanism when the criterion could not be tested**, rather than
  ticking AC-8 because pip printed an error for the wrong reason.
- **Diffing field by field rather than eyeballing.** "Looks the same" would have
  missed a nested schema change. A walk over eleven responses reporting exactly
  one difference is a different kind of statement.
- **Building the comparison tool properly** instead of another throwaway script,
  so the next SDK upgrade starts from a captured baseline.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G21 | Test both ends of a declared version range, not only the newest | medium | backend, infrastructure |
| G22 | Revalidate a plan by executing it when the code has moved underneath it | high | backend, frontend, mobile, infrastructure, content, ops |

Considered and rejected as guardrails:

- "A criterion must have a producible failure condition." Real, and it is close
  enough to G17, prove a test can fail, that a second rule would blur both. The
  AC-8 case is recorded here instead.
- "Diff structured output field by field rather than by eye." Good practice and
  already what `tools/compare_wire.py` enforces by existing. A rule would add
  words without adding behaviour.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **M01 is complete.** Six stories, three of three goals. The `mcp<2` tourniquet
  that S01 applied is off, and the project is on the current SDK line.
- **There is still no CI.** 157 tests, under a second, no key, no network. This
  has been the obvious next infrastructure story for three retros and is now the
  most valuable unstarted work in the project.
- **The live websocket path is still stubbed in every test.** Three stories have
  now verified it by hand with a real key. A recorded session replayed through
  the collector would close that, and would have been useful here.
- **`tools/compare_wire.py` only captures snapshot mode.** Deliberate, so output
  is stable, but it means live behaviour is outside its reach.
- **Descriptions are still unverified against behaviour**, carried from S06.
- **The API key is in the session transcript**, and a Context7 key sits in
  plaintext in `~/.zshrc`. Both still worth rotating.
- **M02 has not been planned.** The obvious candidates are CI, a wider bounding
  box, and the new 2.x surface this migration makes available: middleware,
  prompts, and the streamable HTTP transport for remote clients.
