# Quickstart Validation: Shared OpenDota Response Cache

This guide validates the implemented feature end to end. Behavioral details are defined in
[cache-interface.md](contracts/cache-interface.md); persistent entities and transitions are in
[data-model.md](data-model.md).

## Prerequisites

- Python 3.13+
- `uv`
- macOS or Linux local filesystem
- The `002-shared-response-cache` branch implementation and tests

Install and establish the baseline:

```bash
uv sync --all-groups
uv pip install -e .
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: all lint, format, and offline tests pass. The default test suite makes no live OpenDota
calls and performs no real retry sleeps.

## 1. Fresh response and cross-process reuse

Run the lifecycle integration tests with an isolated cache directory:

```bash
uv run pytest -q tests/integration/test_cache_lifecycle.py \
  -k "fresh_then_hit or process_restart or computer_restart_simulation"
```

Expected:

- the first equivalent request makes one mocked OpenDota call and stores upstream JSON;
- a second server process and a replacement harness reuse the same response;
- reopening the database simulates restart and preserves the original absolute expiry;
- MCP response shaping is identical on hit and miss and can use different draft `include` groups
  without another upstream fetch.

Validate fail-closed GET identity behavior:

```bash
uv run pytest -q tests/unit/test_cache_identity.py \
  -k "query or canonical or api_key or unknown_parameter"
```

Expected:

- reordering the same structured query mapping preserves the digest;
- adding or changing any unclassified query parameter changes the digest without adding that
  parameter to cache-specific code;
- changing only the explicitly excluded `api_key` authentication value preserves the digest;
- excluded credentials never appear in canonical identity bytes, safe descriptions, diagnostics,
  or inspection output.

## 2. Freshness classification and fixed expiry

```bash
uv run pytest -q tests/unit/test_cache_policy.py tests/integration/test_cache_lifecycle.py \
  -k "ttl or parsed or unparsed or clock or expiry"
```

Expected:

- unclassified responses and matches without a confirmed positive parse version use 900 seconds;
- heroes, patches, and confirmed parsed matches use 86,400 seconds;
- hits do not move `created_at` or `expires_at`;
- equality with expiry is a miss, and injected forward/backward clock changes never rewrite the
  stored absolute expiry.

## 3. Twenty-process single-flight success and failure

```bash
uv run pytest -q tests/integration/test_cache_multiprocess.py \
  -k "twenty_callers_success or twenty_callers_retry_exhaustion or owner_crash"
```

Expected:

- 20 equivalent concurrent misses elect one population owner and require one successful upstream
  fetch;
- on exhausted retries, all 20 attached callers receive the same final structured failure and no
  successful entry is stored;
- one later caller starts exactly one new attempt;
- an owner process death releases work through finite lease expiry without exposing partial data.

## 4. Existing process-local pagination regression

```bash
uv run pytest -q tests/unit/test_pagination.py \
  tests/contract/test_tournament_tool.py tests/contract/test_team_tool.py
```

Expected:

- snapshots remain process-local, retain transformed match summaries for 30 minutes, and are
  bounded to 32 concurrent traversals with LRU eviction;
- each continuation consumes the already-materialized summaries without decoding cached raw JSON
  or rerunning service transformation/filtering;
- tokens remain rotating, single-use, query/tool-bound, and replay-safe;
- expiry, eviction, or process replacement returns the existing actionable restart guidance;
- response-cache eviction and clear do not mutate an already-materialized pagination snapshot.

## 5. Capacity, LRU, oversized values, and integrity

```bash
uv run pytest -q tests/unit/test_cache_store.py \
  -k "capacity or expired_first or lru or oversized or corrupt or interrupted_write"
```

Expected:

- committed allocated storage is never above the configured test maximum;
- expired entries are removed before deterministic LRU entries;
- a response larger than an empty store's capacity is returned but not cached and unrelated rows
  remain;
- checksum/length/JSON failures are never hits;
- a terminated writer leaves no incomplete visible row.

## 6. Inspection output and exact counters

Use an isolated directory so operator commands cannot inspect or alter the normal user cache:

```bash
export OPENDOTA_CACHE_DIR="$(mktemp -d)/open-dota-mcp"
export OPENDOTA_CACHE_MAX_BYTES=10485760
uv run pytest -q tests/contract/test_cache_cli.py -k "info or entries or counters or secrets"
uv run open-dota-mcp cache info --json
uv run open-dota-mcp cache entries --limit 50 --json
```

Expected:

- info contains response entry count, stored/allocated/max bytes, hits, misses, writes,
  expirations, evictions, and bypasses;
- generated events match counters exactly;
- entry output is limited, filterable, and has a next cursor when required;
- no fixture API key, Authorization value, raw payload, raw token, or credential-bearing URL appears
  in stdout/stderr.

Benchmark the required inspection scale:

```bash
uv run pytest -q tests/contract/test_cache_cli.py -k "ten_thousand_entries_under_two_seconds"
```

Expected: the cache summary for 10,000 entries completes in under two seconds on the designated
development test machine.

## 7. Confirmed clear during active work

First verify confirmation protection:

```bash
uv run open-dota-mcp cache clear
uv run open-dota-mcp cache info --json
```

Expected: the first command exits with usage status and changes nothing.

Then run the concurrency acceptance test and clear explicitly:

```bash
uv run pytest -q tests/integration/test_cache_multiprocess.py -k "clear_with_active_work"
uv run open-dota-mcp cache clear --yes --json
uv run open-dota-mcp cache info --json
```

Expected:

- active readers finish safely without process shutdown;
- all prior responses, coordination records, and response-cache counters are removed together;
- process-local pagination snapshots in active MCP processes are unchanged;
- all work begun before clear is refused storage on completion;
- work begun after clear can populate;
- the final info result has zero response entries and usage counters.

## 8. Unavailable storage and user-only access

```bash
uv run pytest -q tests/integration/test_cache_lifecycle.py \
  -k "unwritable or corrupt_database or lock_timeout or wrong_owner or permissions"
```

Expected:

- ordinary OpenDota behavior continues when possible and cache failures never become successful
  data;
- diagnostics are actionable, secret-safe, and use stderr/logging;
- created directory/database modes are owner-only;
- another nonprivileged test user cannot read, modify, inspect, or clear the owner's cache on a
  test host that provides multiple user accounts.

## 9. MCP/Codex-compatible regression

```bash
uv run pytest -q tests/contract tests/integration/test_stdio.py \
  tests/integration/test_discovery_to_draft.py
uv run fastmcp inspect src/open_dota_mcp/server.py:mcp
```

Expected:

- exactly three MCP tools remain exposed with their existing slim/group/page schemas;
- no-argument module/console launch reserves stdout for MCP protocol traffic;
- cached and fresh invocations return the same structured contracts in the in-memory client and
  stdio subprocess;
- a Codex-compatible stdio configuration can restart the server and reuse an unexpired response.

## Final quality gate

After implementation remediation, a non-implementing QA sub-agent must independently audit the
required public-surface and risk-based tests, then run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: all three commands pass before implementation completion is reported.
