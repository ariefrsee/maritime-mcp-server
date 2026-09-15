# Retro S06: Validate tool inputs

**Date:** 2026-09-15
**Project:** maritime-mcp-server
**Milestone:** M01
**Branch:** `feat/S06-input-validation`

## 1. Journey

The story got smaller the moment it was investigated properly, and better for it.
"Validate every input" turned into "fix three specific defects", because probing
the running server showed the protocol already rejects every bad type before the
code sees it. The work that remained was semantic, and one of the three was the
most serious defect this project has shipped: a stray space in a filter produced
a confident wrong answer rather than an error.

| Phase | What happened | Key issue |
|-------|---------------|-----------|
| Plan | Probed the live server over stdio before writing anything | Type validation was already handled; the real work was three semantic defects |
| Build | Four changes, no rework. Constraints declared in the signature rather than hand written | Validation turned out to live at the protocol boundary, not in the function |
| Verify | Ten criteria, all over the wire | A criterion phrased "over the wire" turned out to be load bearing |
| Test | Nine cases, seven new tests each proven able to fail | Descriptions are checked for existence, not accuracy |

## 2. Technical findings

### 2.1 The protocol already validated more than expected

**What happened:** the story was planned as "validate tool inputs". Probing the
running server first showed that every bad type is already rejected:

```
radius_nm: "abc"  -> isError, validation error, function never runs
port: 123         -> isError
query: null       -> isError
port missing      -> isError
```

**Why it matters:** direct Python calls do raise `TypeError` and
`AttributeError` on these, which is what an initial look at the code suggests.
No client makes direct Python calls. Planning from the code rather than from the
running system would have produced a story half of which duplicated the
framework.

**Effect:** the story shrank from "validate everything" to three specific
semantic defects, and the plan said so explicitly rather than quietly doing less.

### 2.2 A constraint in the signature beats a check in the body

**What happened:** the obvious fix for a negative radius is
`if radius_nm <= 0: return error`. Instead the bound went into the signature:

```python
radius_nm: Annotated[float, Field(gt=0, le=500, description="...")] = 30.0
```

**Why it is better:** FastMCP turns that into a JSON schema constraint that the
client reads **before** calling:

```json
{"default": 30.0, "exclusiveMinimum": 0, "maximum": 500, "type": "number"}
```

An AI choosing how to call the tool sees the valid range up front. A hand written
check only teaches it after a failed call. Prevention rather than rejection.

### 2.3 The validation is not where the code appears to put it

**What happened:** the constraint sits in the function signature, which reads as
though the function enforces it. It does not:

```
radius -5 direct  -> 0 matches (constraint NOT applied)
radius -5 via mcp -> rejected: ToolError
```

**Why it matters:** the acceptance criteria happened to be phrased "over the
wire", and that turned out to be the difference between a meaningful test and a
worthless one. A test calling `vessels_near_port(-5)` directly would have passed
against both the old and the new code.

**Consequence left in place:** the smoke test calls these functions directly and
therefore gets no input validation. Duplicating the bounds inside the body would
create two places to keep in step. There is now a test recording the bypass
explicitly, so the limitation is written down rather than discovered later.

### 2.4 The worst bug was an asymmetry, not an omission

**What happened:** `search_vessels(flag=" malaysia ")` returned 0. There are 7.

**Why:** `vessels_near_port` had always normalised its input, `key = port.strip().lower()`,
so `" port klang "` worked. The three filters on `search_vessels` compared raw
input. Nobody decided that; the two were written at different times.

**Why it is the most serious defect in this project so far:** it is not a crash
and it does not look wrong. An AI assistant would have relayed "there are no
Malaysian vessels" as fact. Everything else this project has got wrong announced
itself.

## 3. What went wrong

- **The plan said five vessels and there are seven.** Caught by the first command
  run on the branch. **Third time G2 has caught a number written from memory**,
  and the first time inside a story whose entire subject is misleading answers.
  The guardrail keeps working and I keep needing it.
- **The whitespace asymmetry existed for three stories** and was found only
  because this story went looking. No test covered it, nobody hit it, and it
  would have reached whoever used the server first.
- **AC-7 checks that descriptions exist, not that they are true.** If the radius
  ceiling changes and the description does not, nothing notices. That gap is real
  and this story does not close it.
- **The judgement call on whitespace-only filters was mine.** `flag="   "` now
  returns everything rather than nothing. It is consistent with `""` and it is
  still a decision the user did not make. Flagged at the gate, but a gate is a
  weak place to surface a choice buried in a plan's risk table.

## 4. What went right

- **Probing the running server before planning.** It halved the story and stopped
  a duplicate of the framework's own validation being built.
- **Constraints in the signature rather than checks in the body.** The client now
  learns the rules from the schema, which prevents bad calls instead of rejecting
  them.
- **Two isolated reversions rather than one.** Removing filter normalisation
  failed three named tests; removing the blank query check failed four. Each
  failure pointed at one cause, which is worth more than a single revert that
  breaks everything.
- **The S05 test that recorded wrong behaviour as wrong worked exactly as
  intended.** It was written with a docstring saying it must be updated
  deliberately when validation landed. It was, and it forced the change to be
  conscious.
- **Errors still carry provenance.** The blank query error includes the `data`
  block, so even a refusal says whether the server is live or on snapshot.

## 5. New guardrails

| Proposed ID | Rule | Severity | Applies to |
|-------------|------|----------|------------|
| G19 | Normalise the same input the same way everywhere it is accepted | high | backend, frontend, mobile, content, ops |
| G20 | Probe the running system before planning validation, not the source | medium | backend, infrastructure |

Considered and rejected as guardrails:

- "Prefer schema constraints to hand written checks." True here and too
  framework specific to inject into every plan. It belongs in the S06 runbook,
  where someone changing this code will read it.
- "Assert that documentation matches behaviour." The real gap named in section 3,
  and I do not have a rule that would reliably catch it. Writing one that sounds
  good but cannot be followed would be worse than admitting the gap.

**Appended to guardrails.yaml:** [x] yes

## 6. Carry forward

- **Milestone M01 has one story left.** S04, the `mcp` 2.x migration. Its plan
  predates S02, S03, S05 and S06, so re-read section 5 against the current
  `server.py`, which now has a lifespan hook, a source seam, and `Annotated`
  parameter types it did not have then. 157 tests make it far safer than it
  would have been.
- **All three milestone goals are now met.** G1 packaging, G2 tests, G3
  validation. M01 closes when S04 does.
- **Descriptions are unverified against behaviour.** Named in section 3, not
  solved. Worth a thought if the tool surface grows.
- **The smoke test bypasses validation** because it calls the functions
  directly. Recorded in a test and in the runbook.
- **Still no CI.** 157 tests, 0.7 seconds, no key, no network. This is now the
  most obviously worthwhile infrastructure work in the project.
- **The websocket path is still untested.** `_session` is stubbed everywhere.
- **The API key is in the session transcript**, and a Context7 key sits in
  plaintext in `~/.zshrc`. Both still worth rotating.
