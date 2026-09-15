# S07 Runbook: Compact responses

Written for someone who has never opened this repo. Assume they have a laptop, a
terminal, and nothing else.

**Story:** S07 | **Milestone:** M02 | **Date:** 2026-09-15

## 1. What this does

This server answers questions about ships for an AI assistant. The answers were
correct and enormous.

Asking what is near Tanjung Pelepas returned about 6,700 tokens of JSON. An AI
conversation has a limited amount of room to hold things, so three questions
meant a large part of that room was filled with data the assistant reads once,
summarises in a sentence, and never looks at again.

Nothing about the answers changed. Same ships, same facts, same honesty about
what is unknown. They are simply written down in a fifth of the space, and a
single question can no longer return an unbounded amount of it.

You can tell it worked because the same question now costs about 1,271 tokens
instead of 6,678.

## 2. Prerequisites

| Thing | Version | How to check |
|-------|---------|--------------|
| Python | 3.11 or newer. Tested on 3.14.6 | `python3 --version` |
| git | any recent version | `git --version` |

Nothing here needs an API key or a network connection.

## 3. First time setup

```bash
git clone https://github.com/ariefrsee/maritime-mcp-server.git
cd maritime-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Quote the `".[dev]"`: zsh treats square brackets as a pattern.

## 4. Run it

```bash
maritime-mcp-server
```

Unchanged. Silence means it started.

**What is different when you use it.** Both list tools now take a `limit`,
defaulting to 25. Every response reports two numbers:

```
"matches": 67, "returned": 25
```

`matches` is how many qualified, `returned` is how many are in the list. When
they differ the answer was capped, and for a port search the nearest were kept.
An assistant reading that can tell you there are more and offer to widen it.

## 5. Verify it works

**The suite:**

```bash
source .venv/bin/activate
pytest
```

Expect `173 passed`.

**See the size for yourself**, against the committed sample of real AIS traffic:

```bash
python - <<'PY'
import json
from datetime import timedelta
from maritime_mcp_server import server as S
from maritime_mcp_server.store import VesselStore
msgs = json.load(open("tests/data/ais_capture.json"))
store = VesselStore(max_age=timedelta(days=3650))
for m in msgs:
    store.ingest(m)
S.set_store(store)
for limit in (25, 200):
    raw = S.vessels_near_port("Tanjung Pelepas", 40, limit=limit)
    out = json.loads(raw)
    print(f"limit={limit:<4} {len(raw):>6,} chars  ~{len(raw)//4:>5,} tokens  "
          f"matched={out['matches']} returned={out['returned']}")
PY
```

Expect roughly 5,100 characters at the default and 13,600 uncapped. Before this
story the same call returned 26,713.

**Capture and diff**, which is how the change was verified:

```bash
python tools/compare_wire.py --out /tmp/now.json
```

That records eleven responses including the error paths. Compare two captures
with plain `diff` to see that content did not change, only size.

## 6. When it goes wrong

Every row is something that actually happened while building this story.

| Symptom | Cause | Fix |
|---------|-------|-----|
| An answer seems to be missing vessels | It was capped at the default limit of 25 | Read `matches` against `returned`. Pass a higher `limit`, up to 200, or narrow the search |
| `limit` of 0 or 500 is rejected | The allowed range is 1 to 200, published in the schema | Pick a value inside it. The bound exists so one question cannot return an unbounded response |
| A limit outside the range still works | You called the Python function directly rather than through the protocol | Bounds are enforced by the protocol layer. A direct call bypasses them. Same limitation as the radius, documented since S06 |
| Positions have fewer decimal places than before | Deliberate. Four decimals is about 11 metres | AIS is not accurate to sixteen significant figures. The extra digits were noise that looked like data |
| `nearest_port` is missing from a port search | Deliberate. You named the port, so every vessel would carry the same value | It is still present in `search_vessels`, where it carries information |
| `position_age_seconds` is missing from a port search | Deliberate. The `data` block already reports `oldest_position_age_seconds` | Read it there |
| A field is `null` rather than absent | Deliberate, and it costs about 10% | Absent would read as "not sent". Null says "we do not know". That distinction was kept on purpose |
| The response is hard to read by eye | It is no longer indented | Pipe it through `python -m json.tool`. The server's reader is a model, not a person |

## 7. Where things live

| What | Path |
|------|------|
| `_respond`, the single serialisation point | `maritime_mcp_server/server.py` |
| `_PRECISION` and `_tidy`, rounding and redundant fields | `maritime_mcp_server/server.py` |
| The `limit` parameter and its bounds | `maritime_mcp_server/server.py`, on both list tools |
| Size and truncation tests | `tests/test_server.py` |
| Wire capture tool | `tools/compare_wire.py` |
| Project rules learned from retros, now 24 | `.shipline/guardrails.yaml` |

**If you add a tool**, serialise through `_respond` rather than calling
`json.dumps` yourself, and put any numeric field that needs rounding in
`_PRECISION`. Guardrail G19 exists because two code paths treating the same input
differently once produced a confidently wrong answer.

## 8. Rolling back

This story is one commit, merged into `main` and pushed. It changes the shape of
every response, so rolling back restores the larger ones.

To inspect the previous state without changing anything:

```bash
git checkout 322bb72
```

Return with `git checkout main`.

To undo the merge and publish the undo:

```bash
git checkout main
git revert -m 1 <this story's merge commit>
git push origin main
```

**What rolling back costs.** Responses return to roughly five times their current
size, and the `limit` parameter disappears, so a busy port could return an
unbounded list. If something here is wrong, changing the specific rule is almost
certainly better than reverting: the default limit lives on one line, and
`_PRECISION` is a dictionary.

## 9. What in this runbook is unverified

Stated plainly rather than implied to be tested.

- **Every number comes from one 89 vessel fixture.** A live store holds more
  vessels with more static data filled in, so both the absolute sizes and the
  percentages will differ. No live measurement was taken, although a key was
  available.
- **The default limit of 25 was chosen by feel.** Nothing justifies it over 10 or
  50. It silently shapes every answer and deserves revisiting once anyone has
  used this in a real conversation.
- **Whether the old size was actually hurting anything is unobserved.** The
  saving is real and measured. Its effect on a conversation has never been seen,
  because no AI client has ever connected to this server.
- **The rollback commands in section 8 were not executed.** The merge commit hash
  does not exist until the merge does.
- **Only macOS was tested**, on Darwin 24.6.0 with Python 3.14.6 on Apple
  silicon.
