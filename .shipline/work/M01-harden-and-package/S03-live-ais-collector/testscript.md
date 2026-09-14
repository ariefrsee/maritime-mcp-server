# S03 Test Script: Live AIS collector

**Story:** S03 | **Branch:** `feat/S03-live-ais-collector` | **Date:** 2026-09-14

## Instructions

Run each case below yourself. Tick `[x]` when it passes. Leave `[ ]` and write
what happened when it fails. Do not tick a case you did not actually run.

**Run by the assistant on 2026-09-14, at the user's instruction**, as in S01 and
S02. Stated plainly: these results were produced and read by the same party that
wrote the code.

Unlike S02, **most of this needs a live API key and a network connection**, and
several cases take minutes rather than seconds because they wait for real ships
to transmit. Set the key first:

```bash
cd /Users/ariefrse/maritime-mcp-server
export AISSTREAM_API_KEY=your-key-here      # from aisstream.io
source .venv/bin/activate
```

Never paste the key into a file inside the repository.

---

## Prerequisites

- [x] On branch `feat/S03-live-ais-collector`
- [x] Python 3.11 or newer. Tested on 3.14.6
- [x] `pip install .` has been run since the dependency change
- [x] A working `AISSTREAM_API_KEY`

---

## Test cases

### TC1: The server still works with no key at all

**Covers:** AC-7

**Purpose:** Snapshot mode is a supported mode, not a failure. Regressing it
would break every user who has not signed up for a key.

**Steps:**
1. `env -u AISSTREAM_API_KEY python -m maritime_mcp_server.smoke_test`
2. Start the server with no key and call a tool over stdio.

**Expected:** the smoke test passes with `[snapshot]` tags. The server logs
exactly one line about live AIS being off, and tool output carries
`"source": "snapshot"` with 18 vessels.

**Result:** [x] Pass

**Notes:** One stderr line: `AISSTREAM_API_KEY is not set, so live AIS is off
and answers will come from the bundled snapshot.` Not repeated, not an error.

---

### TC2: With a key, real vessels arrive

**Covers:** AC-1

**Purpose:** The point of the story.

**Steps:**
1. Start the server with the key set. Wait five minutes.
2. Call `vessels_near_port` for Tanjung Pelepas at 40 nm.

**Expected:** `"source": "live"`, more than 50 vessels tracked, and names that do
not appear in the bundled snapshot.

**Result:** [x] Pass

**Notes:** 63 vessels tracked. Returned SEA SERENITY, ORKIM RELIANCE,
ZHONG CHUAN 701, CHWNTEK 5. None are among the bundled 18, which are Bunga Mas
Lima, Seri Alam and the rest. Waiting matters: at 150 seconds it was 40 vessels.

---

### TC3: The ships actually move

**Covers:** AC-2

**Purpose:** The strongest possible check. Live data must differ from itself over
time, not merely differ from the snapshot.

**Steps:**
1. With the server running and collecting, call `search_vessels` and keep the result.
2. Wait three minutes. Call it again.
3. Compare positions for vessels present in both samples.

**Expected:** a substantial number changed position, by distances consistent with
their reported speeds.

**Result:** [x] Pass

**Notes:** 35 vessels in both samples, **15 changed position**, moving 0.35 to
0.71 nm in 180 seconds, which is 7 to 14 knots. 28 vessels were new in the second
sample. Three gained type and size during the gap, including SOUTHERN RESPECT
resolving to a 244m tanker bound for SG PEBGC.

---

### TC4: A dead network degrades instead of crashing

**Covers:** AC-3

**Purpose:** The server must survive a feed outage, because the feed carries no
SLA and explicitly does not replay missed events.

**Steps:**
1. Point `collector.ENDPOINT` at an unroutable address and shrink the backoff
   constants so the test finishes.
2. Start the collector and watch it retry.
3. Once it gives up, call a tool.

**Expected:** repeated retries with growing delay, a clear message on giving up,
no traceback reaching the client, and tools falling back to the snapshot.

**Result:** [x] Pass

**Notes:** Four `ConnectionRefusedError` retries, then `Giving up on live AIS
after 4 consecutive failures. The server keeps working from the bundled
snapshot.` `search_vessels` then returned `source: snapshot`, 18 vessels. Tested
against `127.0.0.1:9` rather than by abusing the live service. Re-run after the
D-4 fix with the same result.

**Gap this case did not cover, added as TC9 below:** it tests total failure only.

---

### TC5: The key never escapes

**Covers:** AC-4

**Purpose:** The single highest consequence failure in this story. A leaked key
in a commit is public and permanent.

**Steps:**
1. Run a full live session, capturing every stderr line and every tool response.
2. Search both for the literal key.
3. `grep -rn "$AISSTREAM_API_KEY" . --exclude-dir=.git --exclude-dir=.venv`
4. Read the staged file list before committing, per G6.

**Expected:** zero occurrences everywhere.

**Result:** [x] Pass

**Notes:** `API key present in any stderr line: False`. `API key present in tool
output: False`. Repository grep returns nothing. The collector deliberately logs
the exception **type** rather than its message, because a websocket handshake
failure can echo the request URL and the key rides in the subscription frame.
README uses `your-key-here` as a placeholder.

---

### TC6: Invalid and malformed messages are rejected

**Covers:** AC-6

**Purpose:** AIS transmitters do send messages flagged invalid, and a stream is
untrusted input.

**Steps:**
1. Feed `handle()` a `PositionReport` with `Valid: false`.
2. Feed it malformed JSON, an empty string, `{}`, `[]`, `null`, `None`, an
   integer, and a `SubscriptionConfirmation`.

**Expected:** every one returns `False`, none raises, and the store does not grow.

**Result:** [x] Pass

**Notes:** All eight rejected. The store stayed at one vessel throughout.

---

### TC7: The dependency is declared, not merely present

**Covers:** AC-5

**Purpose:** S01's retro established that a working local environment proves
nothing about what a wheel carries.

**Steps:**
1. `python -m build --wheel`
2. Read `Requires-Dist` and `Requires-Python` from the wheel metadata.
3. Install the wheel into a venv created outside the repository that has never
   held `websockets`.
4. Import the collector from that environment.

**Expected:** `websockets<18,>=17`, `Requires-Python: >=3.11`, and a clean
install that pulls 17.1 and imports.

**Result:** [x] Pass

**Notes:** Both bounds present. Clean environment pulled websockets 17.1 and
mcp 1.30.0, imported the collector, and correctly declined to start without a key.

---

### TC8: Cold start behaves as documented

**Covers:** AC-1, documentation honesty

**Purpose:** The README makes a specific promise about what happens immediately
after launch. If that promise is wrong the documentation is misleading.

**Steps:**
1. Start the server with a key and immediately, within ten seconds, call a tool.
2. Wait two minutes and call again.

**Expected:** the first call returns snapshot data or very few live vessels; the
second returns substantially more. No error either way.

**Result:** [x] Pass

**Notes:** At three seconds the store was empty and the tool returned
`source: snapshot`. At 150 seconds it held 40 vessels and returned `source: live`.
This is the behaviour the README describes, and it is inherent to a stream rather
than a fixable defect.

---

### TC9: A session that works, then fails, then works again

**Covers:** AC-3

**Purpose:** Added after the fact. TC4 tests an endpoint that never connects and
TC2 tests one that never drops. Real operation is neither, and the bug in
divergence D-4 lived exactly in that gap, surviving all seven criteria and all
eight original cases.

**Steps:**
1. Replace `_session` with a stub returning: fail, fail, fail, success, then fail
   forever.
2. Set `MAX_CONSECUTIVE_FAILURES` to 4 and run the collector to completion.
3. Count how many sessions were attempted.

**Expected:** 8 attempts. Three failures, one productive session that resets the
counter, then four more failures before giving up. Without the reset it would
stop at 4.

**Result:** [x] Pass

**Notes:** Exactly 8. This case exists because the bug it covers was found by
reading the code while writing the retro, not by any test.

---

## Coverage check

| AC | Covered by | Passed |
|----|------------|--------|
| AC-1 | TC2, TC8 | [x] |
| AC-2 | TC3 | [x] |
| AC-3 | TC4, TC9 | [x] |
| AC-4 | TC5 | [x] |
| AC-5 | TC7 | [x] |
| AC-6 | TC6 | [x] |
| AC-7 | TC1 | [x] |

## Outcome

- [x] All cases pass. Move to retro.
- [ ] Failures found. List them below, then go back to build.

**Failures and what came of them:**

One real defect was found after all cases had passed, by reading the code while
writing the retro rather than by testing. It is recorded as divergence D-4, it is
fixed, and TC9 was added to cover the gap that hid it. TC4 and the live path were
both re-run after the change.

Two further observations during verification looked like failures and were not,
both recorded as divergences in the plan:

1. **A vessel reported its type but no length.** Looked like a broken merge. The
   vessel transmitted zero hull dimensions and the code correctly refuses to
   report a 0 metre ship. Divergence D-3.
2. **`Nonem` appeared in a verification printout.** A formatting artifact in the
   throwaway test script, not in any product output.

Worth noting what these cases do **not** cover. Every timing sensitive case here
was run once. A stream whose content varies by time of day and traffic could
behave differently at 0300 local, and none of these cases would catch it.
