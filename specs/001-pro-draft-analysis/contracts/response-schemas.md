# Shared Response Schemas and Error Codes

## Error envelope

```json
{
  "error": {
    "status": "error",
    "code": "invalid_page_size",
    "message": "page_size must be between 1 and 100",
    "tool": "list_pro_team_matches",
    "target": "page_size",
    "retry_exhausted": false,
    "retryable_later": false,
    "valid_values": ["1..100"],
    "restart_required": false
  }
}
```

`target`, `valid_values`, and `restart_required` are optional and omitted when they do not apply. Error messages never contain API keys, authorization headers, tracebacks, or unbounded upstream bodies. A draft-item error uses the same shape but sets `error.status` to `unavailable`, `not_professional`, `not_parsed`, or `upstream_error` so a mixed batch can retain usable successful neighbors.

## Sparse diagnostic rules

- A successful response or successful nested item has no generic `status` field.
- `warnings` is optional in the JSON Schema and is serialized only as a non-empty array. Every warning contains `status: warning`, except selection diagnostics, which contain `status: needs_selection`.
- `error` is optional on union types that can succeed and is serialized only for an actual failure. Every error contains its non-OK `status` inside the error object.
- Empty `warnings`, `error: null`, null result placeholders, and a status beside its diagnostic are invalid serialized forms.
- These omission rules apply recursively to response, record, action, and provenance diagnostics. They do not remove substantive domain fields such as `completeness`, `ordering_quality`, `identity_source`, or page `terminal`.

Name ambiguity is a recoverable selection outcome rather than a failed upstream operation:

```json
{
  "query": "dreamleague",
  "candidates": [
    {"league_id": 17272, "name": "DreamLeague Season 30", "tier": "premium"}
  ],
  "warnings": [
    {
      "status": "needs_selection",
      "code": "ambiguous_identity",
      "message": "Choose a league_id from the candidates"
    }
  ]
}
```

## Stable error codes

| Code | Meaning | Retry later |
|---|---|---|
| `invalid_match_ids` | Missing, nonpositive, noninteger, or over-limit draft IDs | no |
| `invalid_include` | Unsupported draft field group | no |
| `invalid_selector` | Missing/both/blank identity selector | no |
| `invalid_page_size` | Page size outside 1–100 | no |
| `invalid_date` | Date is malformed or reversed | no |
| `invalid_filter` | Unsupported side/result | no |
| `identity_not_found` | Stable ID/query resolves to no eligible entity | usually no |
| `ineligible_league` | League exists but is not a professional match surface | no |
| `invalid_continuation` | Malformed, replayed, cross-tool, or query-mismatched token | no |
| `continuation_expired` | Snapshot expired, was evicted, or process restarted | restart traversal |
| `upstream_rate_limited` | Retry budget exhausted after HTTP 429 | yes |
| `upstream_timeout` | Timeout/connect retry budget exhausted | yes |
| `upstream_unavailable` | Retryable server failures exhausted | yes |
| `upstream_rejected` | Nonretryable upstream response | depends on status |
| `upstream_contract` | Malformed/unexpected upstream shape | maybe |
| `cancelled` | Caller cancelled/deadline ended the operation | caller decides |

## Warning codes

The implementation may extend warning codes compatibly, but the initial stable set is:

- `missing_team_id`, `missing_team_name`, `missing_league_name`
- `missing_hero_name`, `missing_patch_version`
- `missing_player_account`, `missing_professional_name`
- `ambiguous_player_mapping`, `unavailable_player_mapping`
- `degraded_draft_order`, `unavailable_draft_timing`
- `inconsistent_duplicate_match`
- `anomalous_team_side`, `missing_result`, `missing_score`
- `reference_enrichment_failed`
- `ambiguous_identity`

## Compatibility rules

- Existing required fields, enum meanings, tool names, and field-group meanings do not change incompatibly within the initial major version.
- New nullable fields or warning/error codes may be added; callers must ignore unknown fields and handle unknown warning/error codes using the `status` inside the emitted diagnostic.
- Optional groups are additive and never remove core fields.
- Unknown OpenDota fields are ignored until deliberately mapped into a documented stable contract.
