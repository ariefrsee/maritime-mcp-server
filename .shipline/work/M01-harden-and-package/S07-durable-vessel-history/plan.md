---
pipeline_state:
  story_id: S07
  milestone: M01
  title: Vessel history that survives a restart
  current_phase: verify     # plan | build | verify | test | retro | deliver | done
  phases_completed: [plan, build, verify]
  approved_by_user: true
  branch: feat/S07-durable-vessel-history
  started_at: 2026-09-15
  last_updated: 2026-09-15
  guardrails_loaded: [G1, G2, G3, G4, G5, G6, G7, G8, G9]
---

# S07: Vessel history that survives a restart

## 1. What this is

The server forgets everything. Positions live in a dict, entries expire after 30
minutes, and stopping the process throws the lot away. Restart it and you wait
the full warm-up again from nothing, because AIS has no backfill to ask for.

That is fine for "what is out there now", which is what this server was built
for. It is fatal for anything that needs to know what happened earlier, and
every use worth having next needs exactly that: when a vessel arrived, how long
it waited, when it berthed. You cannot compute an event from a single snapshot.

After this story the server still answers "now" the same way and just as fast,
but it also remembers, and a restart costs nothing.

## 2. Evidence

Per G2, each fact below came from a command.

**The store is memory only.** `maritime_mcp_server/store.py` is 144 lines holding
`self._vessels: dict[str, dict]`, with `prune()` deleting anything past
`DEFAULT_MAX_AGE = timedelta(minutes=30)`. Nothing writes to disk.

**The cost of forgetting is real and was measured.** A counter left running
across two dev-server restarts:

```
00:55  137 vessels  ->  00:59  157
01:00   13   <- restart, store emptied
01:08  128
01:09   18   <- restart, store emptied
01:20  146
```

Each restart cost roughly ten minutes to get back to a useful fleet.

**Volume is small.** Two independent samples of the live feed over the whole
Malaysian bounding box: 161 positional messages in 4 minutes, and 126 in 3
minutes. Call it 40 per minute, so about 57,600 rows a day. At roughly 60 bytes
a row that is around 3.5 MB a day, 1.3 GB a year unbounded.

**No new dependency is needed.** `sqlite3` is in the standard library, and the
interpreter here carries SQLite 3.53.4:

```
$ .venv/bin/python -c "import sqlite3,sys; ..."
python 3.11.14
sqlite3 3.53.4
```

That matters given G1: every dependency added is a future breaking change, and
this story adds none.

## 3. The shape of the change

The instinct is to replace the dict with a database. That would be wrong, and
the reason is the hot path: `records()` runs on every read, the dashboard reads
every five seconds, and "latest row per MMSI" across a growing history table is
the slow query in this design.

So the dict stays exactly as it is and becomes a **cache of the present**, and
SQLite becomes the **record of the past** behind it.

```
            ingest(message)
                  |
       +----------+-----------+
       |                      |
  in-memory dict         SQLite history
  (latest per MMSI)      (append-only positions)
       |                      |
  records()  <- unchanged  track()  <- new
  fast, no I/O             history queries
```

Reads of "now" never touch disk, so nothing gets slower. Writes append. On
startup the dict is rehydrated from the newest rows in SQLite, so the server
comes back already knowing the fleet.

### Where the file lives

Not inside the package. G3's lesson was that a wheel-installed package cannot be
resolved from `__file__`, and the same install is read-only, so a database there
would fail on first write in exactly the way that is hardest to diagnose.

Resolution order: `MARITIME_MCP_DB` if set, otherwise an OS user-data directory,
created on demand. Tests pass `:memory:`.

### Schema

Two tables. `positions` is append-only, `vessels` is upserted.

| table | columns |
|---|---|
| `positions` | `mmsi`, `observed_at`, `lat`, `lon`, `sog`, `status` |
| `vessels` | `mmsi` primary key, `name`, `type`, `flag`, `length_m`, `destination`, `updated_at` |

Index on `(mmsi, observed_at)`, which serves both "this vessel's track" and
"latest per vessel" on rehydrate.

### Retention

Unbounded growth is not acceptable on a machine nobody is watching. A retention
window, default 90 days, configurable by `MARITIME_MCP_HISTORY_DAYS`, pruned on
the existing prune loop rather than a new timer. 90 days is a deliberate guess
about how far back a port call dispute reaches; it is one constant to change.

Note the two expiries are different things and both stay: 30 minutes decides
whether a vessel is *current*, 90 days decides whether its history is *kept*.

## 4. Scope

In scope:

1. SQLite-backed history behind the existing `VesselStore`.
2. Rehydrate the in-memory cache on startup.
3. Retention pruning.
4. One MCP tool, `vessel_track(query, hours)`, returning a vessel's positions
   over a window. Without a way to read it, persistence is invisible and
   untestable from outside.

Out of scope, written down rather than built (F5):

- Event detection. It is a function over history and belongs in its own story.
- Geofences, port calls, Statements of Facts.
- Migrating the bundled snapshot into the database. It stays a JSON fixture.
- Any change to the dashboard.

## 5. Contract decision (G9)

One behaviour change, surfaced here rather than discovered later.

**After a restart the server answers immediately instead of empty.** Today a
fresh process reports `source: "snapshot"` until AIS fills it. After this, it
reports `source: "live"` straight away using restored positions, which may be up
to 30 minutes old. `position_age_seconds` already states this per vessel and
`oldest_position_age_seconds` states it for the set, so the information is
there. It is still a change in what a caller sees one second after boot, and a
caller that assumed "live means someone transmitted since you started" would be
wrong.

No field is added or removed by this story. `vessel_track` is a new tool, which
is additive.

## 6. Acceptance criteria

Each evaluable at build or verify (G5). None depends on a commit.

1. Ingesting a message writes a row to `positions` and upserts `vessels`.
2. `records()` returns the same values it does today for the same input, proven
   against the existing 199-message fixture.
3. `records()` performs no database read. Asserted by counting queries, not by
   timing, so the test cannot flake.
4. A store constructed over an existing database returns the fleet before any
   new message arrives.
5. Positions older than the retention window are deleted by `prune()`; newer
   ones survive.
6. The 30-minute currency expiry still governs `records()` independently of
   retention.
7. `vessel_track` returns positions oldest first, bounded by the requested
   window, and an empty list rather than an error for an unknown vessel.
8. The database path comes from `MARITIME_MCP_DB` when set, and nothing is ever
   written inside the installed package.
9. `.venv/bin/python -m pytest` passes with no skips introduced.
10. `.venv/bin/python -m maritime_mcp_server.smoke_test` still ends with
    `All smoke checks passed.` without an API key and without leaving a
    database behind in the repository.

## 7. Risks

| Risk | Handling |
|---|---|
| SQLite writes block the websocket read loop | Writes are small and batched per message batch; if a measurement shows otherwise, move to a queue and say so rather than leaving it |
| Concurrency: the collector writes while a tool reads | One connection per thread, WAL mode, and the existing lock still guards the dict |
| The rehydrate makes a cold server look live when it is stale | Covered by the G9 note; `oldest_position_age_seconds` already reports it |
| Tests leave a database file in the repo | `:memory:` in tests, plus criterion 10 checks the smoke test leaves nothing behind |
| Retention default is wrong for real disputes | One constant and one env var; cheap to change once an agent says what they need |

## 8. Out of scope but worth naming

The dashboard currently rebuilds trails from scratch on every page load because
there is nothing to ask for. Once `vessel_track` exists it could load real
history instead. That is a dashboard story, not this one.

## 9. Verify

Both commands from `verify.commands`, on this branch (F4).

```
$ .venv/bin/python -m pytest
168 passed in 0.86s
```

140 before this story, 168 after, no skips. Per file: ais_mapping 72, collector
21, history 22, server 29, store 24.

```
$ .venv/bin/python -m maritime_mcp_server.smoke_test
vessels://all -> [snapshot] 18 vessel(s)

All smoke checks passed.
```

```
$ git status --short | grep -Ei "\.db$|\.sqlite|-wal|-shm"
none
```

### The restart, against the live feed

Two processes in turn over one database, through a real MCP client on stdio:

```
--- first process: cold start, 100s of AIS ---
  after 100s: source=live      vessels=54
--- second process: fresh start, read after 1s ---
  at 1s     : source=live      vessels=54
  restored position ages: min 4s  max 98s
```

Before this story the second process would have answered `snapshot` with 18
vessels and taken ten minutes to catch up. The restored ages are reported
honestly as up to 98 seconds old rather than as fresh.

The database after that run: 28,672 bytes, 64 position rows, 53 vessel rows.

### Acceptance criteria

| # | Criterion | Met | Evidence |
|---|---|---|---|
| 1 | Ingest writes a position row and upserts identity | yes | `test_a_position_message_is_recorded`, `test_identity_is_upserted_not_duplicated` |
| 2 | `records()` returns the same values as before | yes | `test_records_returns_the_same_values_with_history_as_without`, plus all 140 prior tests unchanged |
| 3 | `records()` performs no database read | yes | `test_records_reads_nothing_from_the_database`, counting queries via `set_trace_callback` |
| 4 | A store over an existing database knows the fleet | yes | `test_a_new_store_over_an_existing_database_already_knows_the_fleet`, and the live run above |
| 5 | Retention deletes old positions, keeps new | yes | `test_prune_drops_history_past_the_retention_window`, `test_prune_keeps_history_inside_the_retention_window` |
| 6 | Currency and retention stay independent | yes | `test_currency_and_retention_are_different_questions` |
| 7 | `vessel_track` ordered, bounded, empty not error | yes | six tests under `vessel_track` in test_server.py |
| 8 | Path from env, never inside the package | yes | `test_the_database_path_honours_the_environment`, `test_the_default_path_is_never_inside_the_package` |
| 9 | pytest passes, no new skips | yes | 168 passed |
| 10 | smoke test passes, leaves no database behind | yes | above |

### Scope kept (F5)

One test was written and then removed: that the AIS speed sentinel never reaches
history. It cannot, because `_write_history` maps through `position_fields`, but
that clearing arrived in S06, which is unmerged and not on this branch. Testing
it here would assert another story's behaviour and could not pass (G5). A
comment in `tests/test_history.py` records it as worth adding once S06 lands.

### Follow-ups, not built here

- The dashboard rebuilds trails from scratch on every page load. `vessel_track`
  now exists to give it real history. That is a dashboard story.
- Write batching. At 40 messages a minute each write is one small insert and
  nothing measured suggests it is a problem, so it was not built.
