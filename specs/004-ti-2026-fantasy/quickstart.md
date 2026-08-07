# Quickstart: Validate TI 2026 Fantasy Analysis

This is a runnable validation guide for the completed feature. It references the
[tool contract](contracts/mcp-tool.md), [resource contract](contracts/scoring-resource.md), and
[roster contract](contracts/roster-tool.md) and [data model](data-model.md) rather than duplicating
implementation code.

## Prerequisites

- Python 3.13+
- `uv`
- Repository checked out on `004-ti-2026-fantasy`
- No live OpenDota or web access for automated tests

From the repository root:

```bash
uv sync --dev
```

Never place an API key in fixtures or command output. Optional live validation may use the existing
`OPENDOTA_API_KEY` environment setting.

## 1. Team roster resolution and position safety

```bash
uv run pytest tests/unit/test_roster_mapping.py tests/contract/test_roster_tool.py \
  tests/integration/test_roster_to_fantasy.py -q
```

Expected: exactly one team selector resolves or returns at most 10 candidates; the newest completed
match is tried first and no more than four older records are tried after inconclusive parse/lineup
evidence; exactly five explicit current members are required; the selected match's five IDs must
match them exactly. Clean 2-1-2 lane and distinct ten-minute-farm evidence maps positions 1-5.
Stand-ins, roster changes, incomplete current membership, or membership mismatches return a
cannot-infer error with zero positions and do not search older matches. Missing/tied role evidence
keeps affected positions null without losing otherwise verified IDs.

## 2. Player identity and request validation

```bash
uv run pytest tests/unit/test_identity_resolution.py tests/contract/test_fantasy_tool.py -q \
  -k "identity or candidate or validation"
```

Expected: stable IDs resolve; Unicode NFKC, case folding, punctuation/whitespace-run replacement,
and trimming produce deterministic normalized names; normalized-empty queries fail; only one exact
name auto-selects; collisions/substrings return at most 10 candidates ordered by normalized name
then account ID; no-match and dual selectors fail; invalid counts, dates, tiers, patterns, and
include groups fail before details.

## 3. Post-filter collection and match context

```bash
uv run pytest tests/unit/test_fantasy_mapping.py tests/contract/test_fantasy_tool.py -q \
  -k "filter or order or context or series or empty or coverage"
```

Expected: fixtures spanning at least 30 league-verified maps, public matchmaking records, unknown or
contradictory league provenance, three series, two patches, and all three named tiers are filtered
with AND semantics. Every public or unverified record is excluded before caller filters and the
limit, including with `tournament_tiers=["all"]`; the request schema has no pub/provenance bypass.
Dates are inclusive UTC; limit is applied last; maps are newest first; missing series stays null;
incomplete/abandoned maps do not consume the limit; exhaustive no match succeeds empty. History
pages contain at most 100 records, no request examines more than 500 history records or hydrates more
than 200 unique match details, and either safety limit produces explicit limit-specific truncation.

## 4. Raw statistics and all formulas

```bash
uv run pytest tests/unit/test_fantasy_mapping.py tests/unit/test_fantasy_models.py \
  tests/contract/test_fantasy_tool.py -q -k "raw or formula or scoring or warning"
```

Expected: all required raw keys and 18 score entries exist; exact formulas match the contract; fractional
stuns are preserved; zero, false, and null remain distinct; participation handles zero denominator;
Madstones, Watchers, and lotuses are null with one deduplicated root warning per unavailable stat;
fixtures may contain OpenDota `item_uses.madstone_bundle` and `ability_uses.ability_lamp_use`, but
those counters are never presented as Madstone collection or exact Watcher-capture totals;
Tormentor events map by unique, team-consistent `player_slot` and become null when attribution is
incomplete; Smoke purchases are not counted as uses; the default omits `fantasy_scoring`.

## 5. Scoring resource

```bash
uv run pytest tests/contract/test_fantasy_tool.py -q -k "resource or reference or parity"
```

Expected: the resource lists and reads at `opendota://fantasy/ti-2026/scoring` with JSON MIME type;
it contains one edition, 18 canonical emblems, five exact quality tiers, aggregation, source links,
the frozen five-trait/eight-prefix/eight-suffix inventory, and status/caveat data; unknown effects
are nonnumeric and observed eligibility rates are not modifiers; application order, scope,
prerequisites, and projection semantics support retrospective candidate calculations without
turning configurations into historical match facts; service/resource formulas have exact parity;
reading performs no network request and works outside the repository cwd.

## 6. Retry, cache, and partial failure

```bash
uv run pytest tests/unit/test_opendota_client.py tests/unit/test_cache_identity.py \
  tests/unit/test_cache_policy.py tests/contract/test_fantasy_tool.py -q \
  -k "player_matches or team_players or retry or partial or exhaustion or cancel"
```

Expected: player-history cache identity includes safe path/query values but not secrets; cache hits
avoid I/O; finite retry recovery/exhaustion and `Retry-After` behavior remain intact; concurrency is
bounded; cancellation propagates; usable maps survive record-level failures with sparse warnings.

## 7. MCP discovery and end-to-end journey

```bash
uv run pytest tests/integration/test_roster_to_fantasy.py \
  tests/integration/test_fantasy_journey.py tests/integration/test_stdio.py -q
```

Expected: a Codex-compatible client lists six read-only tools and one resource, resolves a team to
five cross-checked player IDs, passes one ID directly to the fantasy tool, resolves a player in one
call by ID or two calls after ambiguity, obtains a slim default response, opts into scoring, reads
the reference offline, and observes protocol-only stdout. A fixed 20-case corpus spans at least two
players, two candidate emblem configurations, known/null series IDs, unavailable statistics, and
known/unknown modifiers; at least 18 cases must match expected evidence selection, raw and projected
scores, series aggregation, and uncertainty. Candidate configurations and resulting projections are
never reported as observed historical match properties.

## 8. Complete quality gate

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

All commands must pass. Before implementation completion, a separate non-implementing QA sub-agent
must audit public/risk-based coverage and run these gates.

## Optional live smoke test

```bash
uv run python -m open_dota_mcp
```

From an MCP client, read `opendota://fantasy/ti-2026/scoring`, then call
`get_pro_team_roster` for a known professional team and verify the source/current-member
cross-check. Pass one returned account ID to `get_pro_player_fantasy` with `match_count=3`; repeat with
`include=["fantasy_scoring"]`. Validate shape, bounds, null semantics, warnings, and reference URI
rather than hard-coded current patch or live values.
