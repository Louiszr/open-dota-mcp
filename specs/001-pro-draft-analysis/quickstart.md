# Quickstart Validation Guide

This guide is the Phase 1 acceptance/run contract. Commands become runnable after the implementation tasks create the scaffold described in [plan.md](plan.md).

## Prerequisites

- Python 3.13+
- `uv`
- Optional: `codex` CLI for the local compatibility scenario
- Network access only for the live smoke test; the default quality suite is offline

## Install and run quality checks

From the repository root:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected outcome: dependency resolution succeeds in a clean environment; Ruff reports no violations or formatting changes; every unit, contract, integration, retry, cancellation, snapshot, and stdio test passes without contacting OpenDota or sleeping in real time.

## Inspect the server contract

```bash
uv run fastmcp inspect src/open_dota_mcp/server.py:mcp
```

Expected outcome: exactly `get_pro_match_drafts`, `list_pro_tournament_matches`, and `list_pro_team_matches` are listed, each with typed inputs, descriptions, and object output schemas matching [mcp-tools.md](contracts/mcp-tools.md). Successful output schemas permit sparse omission of generic `status`, empty `warnings`, and absent `error` fields.

Start the stdio server directly only for a client process (it waits for MCP protocol input):

```bash
uv run python -m open_dota_mcp
```

Expected outcome: no banner or diagnostic text is written to stdout; an MCP initialize request succeeds and diagnostics, if any, go to stderr.

## Validate with Codex

The official Codex MCP configuration supports local stdio commands and project-scoped `.codex/config.toml`. For a public-access smoke test, register the server from the repository root using an absolute path:

```bash
codex mcp add open-dota -- uv --directory /absolute/path/to/open-dota-mcp run python -m open_dota_mcp
codex mcp list
```

Restart the Codex client after adding the server, then use `/mcp` to confirm `open-dota` is active and the three tools are discoverable.

For optional API-key access, export `OPENDOTA_API_KEY` in the Codex host environment and configure forwarding rather than placing the secret in repository files:

```toml
[mcp_servers.open-dota]
command = "uv"
args = ["--directory", "/absolute/path/to/open-dota-mcp", "run", "python", "-m", "open_dota_mcp"]
env_vars = ["OPENDOTA_API_KEY"]
```

Expected outcome: the key never appears in tool output, errors, logs, or inspected schemas. Public operation still works when the variable is absent.

## End-to-end scenarios

Use current known professional IDs for the live smoke test; deterministic examples live in test fixtures.

### 1. Tournament discovery to draft

1. Call `list_pro_tournament_matches` with a known `league_id` and `page_size: 2`.
2. Verify newest-first records, both team sides, winner/score, and page metadata; clean records omit `status`, `warnings`, and `error`.
3. Pass one returned ID to `get_pro_match_drafts` with no include groups.
4. Verify the compact core, all draft actions, authoritative/degraded order status, hero labels, and pick-only player identity.

Expected outcome: the known-ID workflow takes two tool calls, response sizes are bounded, and no raw upstream sections appear.

### 2. Name disambiguation

1. Call the tournament tool with a broad `tournament_name` fixture and the team tool with a reused `team_name`/tag fixture.
2. Verify each returns no more than 10 deterministic candidates plus a non-empty warning carrying `status: needs_selection`, with no silently selected entity.
3. Repeat using the chosen stable ID.

Expected outcome: exact normalized matches resolve automatically; ambiguous substrings require the explicit second call.

### 3. Team filters

Call `list_pro_team_matches` with a known team ID, inclusive start/end dates, `side: radiant`, `result: win`, and a small page size.

Expected outcome: every record falls inside the UTC date range and is a Radiant win from the selected team's perspective. A valid no-result filter returns an empty terminal page rather than an error.

### 4. Stable continuation snapshot

1. Request the first tournament/team fixture page and save its continuation token.
2. Mutate the fake upstream fixture by adding a newer match.
3. Follow the saved token to terminal and verify no repeat/skip and no new match.
4. Start again without a token and verify the new match appears first.
5. Replay an old token and exercise an expired token.

Expected outcome: active traversal is immutable; replay/mismatch/expiry returns structured restart guidance with non-OK status nested inside `error`.

### 5. Partial drafts and response groups

Run fixture-backed draft calls for complete, missing-label, missing-professional-name, ambiguous-player, nonprofessional, unparsed, and degraded-order matches. Repeat with each include group individually and all groups together; request one invalid group.

Expected outcome: valid neighbors remain usable, Steam32 is the only display fallback, persona names never appear, degraded drafts retain upstream sequence, optional groups are additive, and an invalid group produces no partial result. Clean successes omit generic status and empty diagnostics; warning/error fixtures emit only non-empty diagnostics with their non-OK status nested inside. Repeated requested IDs are silently processed once at their first position with no `duplicates_omitted` field or duplicate warning.

### 6. Retry and cancellation

Run the focused client tests:

```bash
uv run pytest tests/unit/test_opendota_client.py -q
```

Expected outcome: fixtures prove 429 `Retry-After` handling, fallback jitter, eligible timeout/5xx recovery, retry exhaustion, nonretryable failures, oversized delay rejection, and immediate cancellation with injected clock/sleeper functions and no real delays.

## Release gate

Before implementation is reported complete, a non-implementing QA sub-agent must audit public/risk-based coverage and independently run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

All three commands must pass after any remediation. The live OpenDota smoke test is supplementary and must not make the default suite network-dependent.
