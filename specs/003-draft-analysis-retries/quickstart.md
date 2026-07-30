# Quickstart: Validate Reliable Retries and Team Drafting Report

This guide describes runnable validation scenarios for the completed feature. It intentionally
references the [MCP contract](contracts/mcp-tool.md) and [data model](data-model.md) instead of
duplicating implementation code.

## Prerequisites

- Python 3.13+
- `uv`
- Repository checked out on `003-draft-analysis-retries`
- No live OpenDota access is required for the automated suite

From the repository root:

```bash
uv sync --dev
```

Do not place an API key in test fixtures or command output. Live manual validation may use
`OPENDOTA_API_KEY` through the existing environment configuration, but automated acceptance tests
must use mocked transports and temporary caches.

## 1. Retry recovery and exhaustion

Run focused client tests:

```bash
uv run pytest tests/unit/test_opendota_client.py -q
```

Expected coverage:

- fallback bases 2/4/8/16/32 with additive jitter inside 0-20%;
- missing, blank, zero, negative, non-finite, malformed, expired, and date-form guidance;
- repeatedly short guidance cannot undercut safe fallback;
- long usable guidance is honored when it fits;
- attempts, 40-second delay, 75-second accumulated, 90-second elapsed, and caller-deadline gates
  stop before an extra sleep/request;
- HTTP 408/429/500/502/503/504 and eligible timeout/network failures recover or exhaust;
- nonretryable failures are issued once;
- cancellation interrupts requests and retry waits;
- tests inject clocks/sleepers and perform no real waiting.

The default maximum-jitter fallback sequence should total 74.4 seconds and remain within the
75-second accumulated budget.

## 2. Cache coordination

```bash
uv run pytest tests/integration/test_cache_multiprocess.py -q
```

Expected outcome: equivalent concurrent cache misses have one population owner and one retry
sequence. Waiters receive the same successful payload or exhausted failure. Cache hits issue no
HTTP request; waiter cancellation does not cancel or duplicate the owner.

## 3. Default report selection and coverage

```bash
uv run pytest tests/contract/test_analysis_tool.py -q -k "default or coverage or empty"
```

Expected outcomes:

- the latest valid patch is chosen by release date, not catalog position/ID;
- default tier is `[premium]` (Tier 1);
- the newest 25 completed matches consume quota before parse/filter work;
- parsed + unparsed equals examined count in compact coverage;
- unparsed and filtered matches do not expand into diagnostic outcomes;
- a valid no-eligible-game request succeeds with `matches=[]`;
- an unknown team and unavailable default patch return structured guidance.

Use the fixtures to verify exact results; do not rely on today's live latest patch.

## 4. Patch, tier, and scenario filters

```bash
uv run pytest tests/contract/test_analysis_tool.py -q -k "pattern or tier or side or result or first_ban"
```

Expected outcomes:

- `7[.]4[01]` uses full-string matching and admits only `7.40`/`7.41` labels;
- malformed, over-64, and timeout-inducing patterns fail before detail retrieval;
- named tiers combine, `all` is exclusive, and all invalid-tier errors enumerate four choices;
- side, result, and first ban combine with AND semantics from the selected team perspective;
- unknown first-ban/team-side/tier/patch values are never guessed or exposed as filter evaluations.

## 5. Optional evidence groups

```bash
uv run pytest tests/unit/test_analysis_mapping.py tests/contract/test_analysis_tool.py -q -k "draft or lanes or economy or structures or objectives"
```

Expected outcomes:

- slim default has no optional group;
- each group is independently additive and all five can be combined;
- comparisons consistently use the analyzed-team perspective;
- draft chronology, per-team pick/ban run numbering, unique player association, and matchup
  knowledge match source fixtures;
- heroes are name strings, never ID/name structs;
- checkpoint lookup uses the latest aligned sample at or before 600/1200/1500 seconds without
  exposing sample timestamps;
- lane XP/last-hit and economy gold fields contain only supported facts, and `gold_t` checkpoint
  values are not relabeled as exact net worth;
- structure counts use attributable timestamped destruction events, not final bitmask timing;
- structure output uses compact keys rather than zero-filled counter trees;
- Roshan/Tormentor event lists use `[]` for verified zero and `null` for unavailable/not applicable;
- incomplete evidence becomes `null`/omission, never a fabricated zero, identity, or reason object.

## 6. Pagination

```bash
uv run pytest tests/contract/test_analysis_tool.py tests/integration/test_analysis_journey.py -q -k "page or cursor or journey"
```

Expected outcomes:

- first pages default to 10 and reject sizes outside 1-25;
- a 100-match quota's eligible results are traversable newest-first with no repeats/skips;
- continuation calls perform no upstream work;
- every page repeats identical team, filters, and compact coverage;
- cursors rotate and reject replay, mismatch, cross-tool use, expiry, eviction, and process restart
  with correction/restart guidance.

## 7. MCP schema and stdio journey

```bash
uv run pytest tests/integration/test_stdio.py tests/integration/test_analysis_journey.py -q
```

Expected outcome: a Codex-compatible client can list the fourth read-only tool, resolve a team ID
with the existing lookup flow, request the default report in one call, opt into all five groups,
and follow only returned cursors. Contract assertions reject team tags, unlikely lookup IDs,
filter-evaluation/source fields, and broad diagnostics. Stdout contains MCP
protocol traffic only; retry/cache diagnostics remain on stderr/logging.

## 8. Complete quality gate

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

All three commands must pass. Before implementation completion, a separate non-implementing QA
sub-agent must audit public/risk-based test coverage and run these gates, as required by the
constitution.

## Manual live smoke test (optional)

Start the stdio server through the existing MCP client configuration:

```bash
uv run python -m open_dota_mcp
```

Use a known positive professional team ID. First invoke `analyze_pro_team_drafts` with a small
lookback such as 3 and no include groups. Confirm the selected patch/tier, coverage, bounded core,
and optional cursor. Then repeat with `include=["draft"]`. Live upstream data may be partial and
the current patch changes over time; validate shape/invariants rather than hard-coded match facts.
