# Lean Response Schema and Error Contract

## Serialization rules

- Successful responses have no generic `status` or `error` field.
- Optional groups are absent unless requested.
- Within requested groups, unsupported scalar values are `null` or omitted.
- A verified count may be zero and a verified event collection may be empty.
- Public responses do not include provenance, source, evidence quality, availability,
  completeness, filter evaluation/disposition, warning arrays, or diagnostic reason wrappers.
- Team and match IDs are retained because they support follow-up calls. Team tags and league,
  patch, hero, action-source, and player-account IDs are excluded.
- Heroes are localized-name strings, not identity structs.
- API keys, authorization headers, credential-bearing URLs, tracebacks, upstream headers, and full
  upstream bodies are never serialized.

## Request-wide error

```json
{
  "error": {
    "code": "invalid_tournament_tiers",
    "message": "Use named tiers or all by itself",
    "valid_values": ["premium", "professional", "amateur", "all"]
  }
}
```

Only `code` and `message` are universal. `valid_values` is added when it directly helps correct an
enum input. Cursor errors may add `restart_required: true`.

## Retry exhaustion

```json
{
  "error": {
    "code": "upstream_rate_limited",
    "message": "OpenDota rate-limit recovery exhausted the delay budget",
    "reason": "delay_budget",
    "retry_after_seconds": 38.2
  }
}
```

`retry_after_seconds` appears only when a safe actionable delay is known. Attempt counts, selected
delay source, accumulated wait, elapsed time, required-delay calculations, and raw guidance remain
in structured logs rather than the MCP response.

## Stable validation and error codes

| Code | Meaning | Correction/retry |
|---|---|---|
| `invalid_team_id` | Missing or nonpositive ID | Use a positive stable ID |
| `identity_not_found` | Team ID has no resolved team | Resolve the name through existing lookup |
| `invalid_lookback_count` | Outside 1-100 | Use 1-100 |
| `invalid_version_expression` | Blank, too long, malformed, or timed-out regex | Correct or simplify the full-string expression |
| `patch_catalog_unavailable` | No valid dated default label | Supply a version pattern or retry later |
| `invalid_tournament_tiers` | Invalid tier selection | Use named tiers or `all` alone |
| `invalid_filter` | Unsupported side/result/first-ban | Use the documented enum |
| `invalid_include` | Unsupported or duplicate group | Use the five documented groups |
| `invalid_page_size` | Outside 1-25 | Use 1-25 |
| `invalid_continuation` | Malformed, replayed, or mismatched | Restart the first page |
| `continuation_expired` | Snapshot no longer exists | Restart the first page |
| `upstream_rate_limited` | 429 retry policy exhausted | Retry later |
| `upstream_timeout` | timeout retry policy exhausted | Retry later |
| `upstream_unavailable` | network/server retry policy exhausted | Retry later |
| `upstream_rejected` | nonretryable OpenDota response | Depends on response |
| `upstream_contract` | unexpected upstream shape | Retry later/report incompatibility |
| `cancelled` | caller cancellation/deadline | Caller decides |

Internal filter and evidence reason codes are not part of the public compatibility contract.

## Retry diagnostic log contract

Structured logs may contain the operation name, safe failure/status class, attempt number, delay
source, selected finite delay, and exhaustion reason/budget observations. They must not contain
credentials, credential-bearing URLs, bodies, raw `Retry-After`, or arbitrary headers.

## Pagination invariants

- `len(matches) <= page_size <= 25`.
- Across one immutable traversal, every eligible match appears once in descending
  `(start_time, match_id)` order.
- Every page repeats the same `team`, `filters`, and `coverage` values.
- Nonterminal pages include `next_cursor`; terminal pages omit it.
- A cursor cannot be used across tools or normalized requests.
