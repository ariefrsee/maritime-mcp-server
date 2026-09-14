# Retro S03: Live AIS collector

**Date:** 2026-09-14
**Project:** maritime-mcp-server
**Milestone:** M01
**Branch:** `feat/S03-live-ais-collector`

## 1. Journey

The smallest story of the three and the only one that produced something a person
can see. The collector is about a hundred lines including comments, and it went in
without a single surprise about the protocol, because S02 had already made every
mistake worth making. What this story hit instead were decisions: which Pythons to
support, what counts as a failure worth backing off from, and what a stream can
honestly promise a client that expects a database.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Written during the S02 split, checked against the code S02 left behind | Still accurate. The `set_store` seam was exactly what was needed |
| Build | Three steps, no rework | A dependency forced a change to what the package promises |
| Verify | Seven of seven, driven over the real protocol against the real service | Two results looked like defects and were not |
| Test | Eight cases, all passing, several taking minutes because they wait for ships | Every timing sensitive case was run once |

## 2. Technical findings

### 2.1 A clean close is a failure, not a success

**What happened:** the obvious retry loop treats `_session()` returning normally
as success and reconnects at once.

**Why that is wrong:** a server that accepts the connection and immediately
closes it, which is what a rejected or rate limited key looks like, returns
normally. The loop then reconnects instantly, forever, against a free service
with no SLA. The most likely way to lose access to this feed is to abuse it while
believing the code is healthy.

**Fix:** a clean return increments the same failure counter an exception does.
Only inbound messages count as success.

```python
try:
    await self._session()
    failures += 1          # a clean close still counts
except Exception:
    failures += 1
```

With `MAX_CONSECUTIVE_FAILURES = 8` the collector abandons a persistently unhappy
endpoint rather than hammering it.

### 2.2 Log the exception type, never its message

**What happened:** the natural line is `log.warning("connection failed: %s", exc)`.

**Why that is dangerous here:** a websocket handshake failure can echo the
request, and the subscription frame carries the API key. A library that includes
the URL or the first frame in an exception message would put the key straight
into the log, which is the one place people paste when asking for help.

**Fix:**

```python
log.warning("AIS connection failed (%s), retry %d in %.0fs",
            type(exc).__name__, failures, delay)
```

Verified across a full live session: `API key present in any stderr line: False`.

### 2.3 A stream cannot satisfy a client that expects a database

**What happened:** the server starts knowing nothing and fills over minutes. At
three seconds it held zero vessels; at 150 seconds, 40; at five minutes, 63.

**Why it cannot be fixed here:** aisstream does not replay missed events. There is
no backfill to request. An MCP server is launched and killed by its client, so
this happens on every single start.

**What was done instead:** documented precisely in the README, covered by TC8, and
made harmless by the snapshot fallback plus the provenance block. A cold client
gets a labelled snapshot rather than an empty answer or an error.

### 2.4 Absent is not zero

**What happened:** MARQUIS DE PRIE gained a type and destination but kept
`length_m: null`, which read as a merge bug.

**Why it is correct:** `ShipStaticData` carries `Dimension`, and that vessel
transmitted zeroes. `length_from_dimension` returns `None` for a zero total
rather than reporting a 0 metre ship. G8 written in S02, working in S03 without
anyone having to remember it.

## 3. What went wrong

- **A dependency quietly dictated the project's Python floor.** `websockets` 17
  requires 3.11 and the project promised 3.10. Adding a library narrowed what the
  package supports, which is not a consequence anyone expects from "add a
  websocket client". It was caught only because G1 forces a deliberate look at
  every dependency's bounds.
- **Every timing sensitive test was run once.** TC2, TC3 and TC8 all depend on
  real traffic at one time of day. The Strait is busy at midday and thinner at
  0300, and nothing here would notice if the thresholds failed then. TC2's
  "more than 50 vessels" could plausibly fail at night with the code entirely
  healthy.
- **The retro for S02 said milestone goal G2, real tests, was overdue. It is now
  three stories overdue** and this story added the first code with genuine
  concurrency in it. A retry loop with backoff and a give-up threshold is exactly
  the kind of logic that rots silently, and it is currently verified by one manual
  run against a fake endpoint.
- **The collector's failure counter was never reset on success.** After eight
  cumulative failures spread across hours of healthy operation it would have
  given up, and a long running server that hiccups occasionally would silently
  serve the snapshot forever. **Found while writing this retro, not while
  testing.** Eight acceptance criteria and eight test cases all passed over a
  broken retry policy, because every one of them exercised either total failure
  or total success, and never the mixed case that real operation is made of.
  Fixed, and re-verified. Divergence D-4.

## 4. What went right

- **S02 absorbed all the protocol pain.** Not one surprise about message shapes,
  field names or envelopes, because they were all discovered a story earlier
  against real captured traffic. The split paid for itself here.
- **Raising the Python floor went to the user rather than into the build.** G9,
  written one story ago, caught exactly the class of change it was written for.
- **Fixing the retry bug rather than carrying it forward.** The first instinct
  was to log it and move on, with the excuse that changing retry semantics after
  verification would invalidate the run. That reasoning was weak: the fix was one
  line and re-verification took minutes. Shipping a known silent degradation to
  save a re-run would have been the wrong trade.
- **Testing the failure path against an unroutable address** rather than against
  the real service. It proved the same behaviour without risking the account the
  whole story depends on.
- **Driving the real server over stdio for every criterion** instead of calling
  functions directly. That is what caught the cold start behaviour honestly and
  is why TC8 exists.
- **AC-2 asked the right question.** "Different from the snapshot" would have
  passed trivially and proved nothing. "Different from itself three minutes later"
  is the criterion that actually demonstrates live data, and it is the one that
  produced the most convincing evidence in the project so far.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G13 | Never log an exception's message where a secret could be in scope | critical | backend, infrastructure, ops |
| G14 | Treat a clean disconnect as a failure for retry purposes | high | backend, infrastructure |
| G15 | Say when a criterion was verified once against conditions that vary | medium | backend, frontend, mobile, infrastructure, content, ops |
| G16 | Test the mixed case, not only total success and total failure | high | backend, infrastructure, ops |

Considered and rejected as guardrails:

- "Check a new dependency's requires-python before adding it." Real, but it is
  one instance of G1, which already forces a deliberate look at a dependency's
  bounds. A second rule would dilute rather than add.
- "Always test against a fake endpoint rather than the real service." Too broad.
  Most of this story's value came from testing against the real service. The
  narrow truth is that destructive or abusive cases get a fake, which is closer
  to ordinary judgement than to a rule worth injecting into every plan.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **Milestone goal G2, real tests, is now three stories overdue** and is the only
  unfinished goal in M01. The collector's retry logic, the store's merge and
  eviction, and the mapping tables all deserve assertions rather than a human
  reading output.
- **S04, the `mcp` 2.x migration, is the last planned story** and its plan was
  written before S02 and S03 existed. Re-read its section 5 against the current
  shape of `server.py`, which now has a lifespan hook it did not have then.
- **`tools/compare_wire.py` is still unwritten** and is still the right way to
  verify S04.
- **The bounding box is hardcoded** in `collector.py`. Making it configurable is
  a small change and would let the server cover somewhere other than Malaysia.
- **The API key is in this session's transcript.** Rotating it at aisstream.io
  costs nothing.
- **Still open from S01:** input validation, and `pyproject.toml` declares MIT
  with no LICENSE file in the repository.
