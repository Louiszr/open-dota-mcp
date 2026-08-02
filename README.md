# OpenDota Professional Analysis MCP

A local, read-only stdio MCP server for compact professional Dota 2 match discovery, ordered
draft evidence, and team-relative drafting reports. It exposes exactly four tools and works
without an API key by default.

## Install and verify

Python 3.13 and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv python install 3.13
uv sync --all-groups
uv pip install -e .
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Inspect the contract with `uv run fastmcp inspect src/open_dota_mcp/server.py:mcp`. Start it for an MCP client with `uv run python -m open_dota_mcp`; stdio is protocol-only, so an interactive terminal appears idle.

## Codex registration

From this repository, substitute its absolute path:

```bash
codex mcp add open-dota -- uv --directory /absolute/path/to/open-dota-mcp run python -m open_dota_mcp
codex mcp list
```

Restart Codex and use `/mcp` to confirm the server. Public operation sends no authentication. For higher upstream limits, export `OPENDOTA_API_KEY` in the Codex host environment and forward it with `env_vars = ["OPENDOTA_API_KEY"]`; never place the secret in `.env.example` or command arguments. The client sends it only as a Bearer header and masks errors.

## Tools and efficient workflows

- `get_pro_match_drafts`: accepts 1–10 positive match IDs, silently de-duplicates them, and preserves first occurrence. Its slim core contains all draft actions. Add `competition`, `result`, `draft_timing`, and/or `provenance`; unsupported groups fail before upstream I/O.
- `list_pro_tournament_matches`: select exactly one professional `league_id` or `tournament_name`. Pages default to 20 and max at 100. Ambiguous names return at most ten candidates.
- `list_pro_team_matches`: select one `team_id` or team name/tag. Inclusive `YYYY-MM-DD` UTC dates, `radiant`/`dire`, and team-relative `win`/`loss` filters combine with AND semantics. Pages use the same 20/100 limits.
- `analyze_pro_team_drafts`: supply a positive stable `team_id` to analyze the newest 25 completed
  matches by default, or set `lookback_count` from 1–100. The quota is consumed before parse status
  and filters. The default is the latest dated catalog patch and `[premium]` (Tier 1). A custom
  `version_pattern` uses full-string regex matching with a 64-character limit and a 50 ms
  evaluation timeout. `tournament_tiers` accepts distinct combinations of `premium`,
  `professional`, and `amateur`, or `all` by itself. Team-relative `side`, `result`, and
  `first_ban` filters combine with AND semantics.

The report's slim default contains resolved team/filter context, aggregate `examined`/`parsed`/
`unparsed` coverage, and compact match outcomes including opponent IDs. Add any distinct subset of
`draft`, `lanes`, `economy`, `structures`, and `objectives`. Draft evidence preserves authoritative
chronology, per-team pick/ban rounds, unique players, and known lane opponents. Lane and economy
samples use the latest aligned observation at or before 10/20 minutes. Economy team differences
come directly from `radiant_gold_adv` and `radiant_xp_adv`, inverted when the analyzed team is
Dire; missing advantages are not reconstructed from player data. Both teams' per-hero total gold
and experience come from aligned `gold_t` and `xp_t` series. `gold_t` is described as total gold,
not exact net worth. Missing series/checkpoints stay `null`, while a verified numeric zero remains
`0`. Structures use attributable timestamped losses. Roshan and
Tormentor lists cover events through 25 minutes. A verified empty list means none; `null` means the
checkpoint is unavailable or not applicable. Sparse evidence is never guessed.

With a stable league/team ID, call a discovery tool and pass a returned match ID to the draft tool:
two calls. Resolve a team name through `list_pro_team_matches`, then pass its stable ID to the
analysis tool. Analysis pages default to 10 eligible matches and allow at most 25. Follow only
`next_cursor`; continuation performs no OpenDota I/O and repeats unchanged team, filters, and
coverage. All traversal tokens are single-use, snapshot-bound, expire after 30 minutes, and are
lost on server restart; restart without a token to include newer matches.

Expected validation, ambiguity, partial-data, and upstream failures are sparse structured diagnostics. Clean successes omit generic status, empty warnings, and null errors. Labels can be null while authoritative numeric IDs remain. Player display identity uses a professional name or explicitly marked Steam32 fallback—never a Steam persona name.

## Shared response cache

Successful OpenDota GET responses are retained in an owner-only SQLite cache across local MCP
processes and restarts. Most responses have a fixed 15-minute lifetime; heroes, patches, and
confirmed parsed matches have a fixed one-day lifetime. Hits never extend expiry, failures are not
stored, and cache failures fall back to ordinary upstream behavior without serving stale data.

The cache defaults to the platform user-cache directory and a retained main-database maximum of
1 GiB. Override these with `OPENDOTA_CACHE_DIR` and `OPENDOTA_CACHE_MAX_BYTES`. Inspect bounded,
credential-free metadata with `open-dota-mcp cache info [--json]` and
`open-dota-mcp cache entries [--limit 1..500] [--json]`. Remove response and usage state with
`open-dota-mcp cache clear --yes`; generation protection prevents older in-flight requests from
repopulating it. Pagination snapshots remain separate, process-local, bounded to 32 traversals,
and unaffected by inspection, eviction, or clear. Never put an API key in cache paths or command
arguments.

## Finite retry policy

Every repeatable OpenDota GET uses one cache-population-owner retry sequence. Defaults permit six
total attempts with fallback bases of 2, 4, 8, 16, and 32 seconds plus independently sampled
additive 0–20% jitter. One delay is capped at 40 seconds, accumulated retry delay at 75 seconds,
and monotonic total elapsed time at 90 seconds. A positive finite standard `Retry-After` seconds or
future HTTP date is honored only when it is at least the safe fallback and fits every active
budget. Invalid, expired, non-finite, zero, negative, and repeatedly short guidance cannot cause an
immediate retry. Cancellation remains prompt, cache hits make no upstream request, and concurrent
waiters do not create more retry sequences.

Configure these bounds with `OPENDOTA_MAX_ATTEMPTS`, `OPENDOTA_RETRY_BASE_DELAYS`,
`OPENDOTA_RETRY_JITTER_RATIO`, `OPENDOTA_RETRY_DELAY_CAP`, `OPENDOTA_RETRY_DELAY_BUDGET`, and
`OPENDOTA_RETRY_ELAPSED_BUDGET`. Exhausted errors identify the finite reason and include a safe
`retry_after_seconds` only when upstream supplied one; raw headers, bodies, URLs, credentials, and
engine diagnostics are never public.

## Troubleshooting

- `continuation_expired`: the 30-minute snapshot expired, was evicted, or the process restarted. Begin the same query without a token.
- `invalid_continuation`: a token was replayed, crossed between tools, or accompanied by mismatched inputs. Use only its latest replacement token.
- `upstream_rate_limited`/`upstream_unavailable`: the finite retry budget was exhausted. Retry later; optionally configure a key through the host environment.
- No stdout output when launched manually is expected: stdio waits for MCP protocol input. Diagnostics go to stderr.
- All automated tests are deterministic and offline. Live OpenDota availability is required only during actual use.
