# OpenDota Professional Analysis MCP

A local, read-only stdio MCP server for compact professional Dota 2 match discovery and ordered draft evidence. It exposes exactly three tools and works without an API key by default.

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

With a stable league/team ID, call a discovery tool and pass a returned match ID to the draft tool: two calls. With an ambiguous name, choose a candidate ID first: three calls. Continue a collection by sending the opaque token alone. Tokens are single-use, snapshot-bound, expire after 30 minutes, and are lost on server restart; restart without a token to include newer matches.

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

## Troubleshooting

- `continuation_expired`: the 30-minute snapshot expired, was evicted, or the process restarted. Begin the same query without a token.
- `invalid_continuation`: a token was replayed, crossed between tools, or accompanied by mismatched inputs. Use only its latest replacement token.
- `upstream_rate_limited`/`upstream_unavailable`: the finite retry budget was exhausted. Retry later; optionally configure a key through the host environment.
- No stdout output when launched manually is expected: stdio waits for MCP protocol input. Diagnostics go to stderr.
- All automated tests are deterministic and offline. Live OpenDota availability is required only during actual use.
