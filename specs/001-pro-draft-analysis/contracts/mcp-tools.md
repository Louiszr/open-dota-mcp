# MCP Tool Contract

The server exposes exactly these three read-only tools. All successful and expected domain-failure results are structured JSON objects. Timestamps are UTC ISO 8601 strings with `Z`; unknown labels are `null`; numeric identifiers are retained.

## `get_pro_match_drafts`

Use when the caller already has professional match IDs and needs ordered pick/ban evidence. The default response is the compact match/draft core; optional groups are additive.

### Input

| Parameter | Type | Required | Contract |
|---|---|---|---|
| `match_ids` | integer[] | yes | 1–10 positive IDs in caller order |
| `include` | string[] | no | Unique subset of `competition`, `result`, `draft_timing`, `provenance`; default `[]` |

Duplicate IDs are silently processed once at their first position. `requested_match_ids` contains that normalized first-occurrence list; no `duplicates_omitted`, count, or warning is returned. An invalid include value rejects the request before any upstream work and returns the valid values.

### Core output

```json
{
  "requested_match_ids": [8123456789],
  "matches": [
    {
      "match_id": 8123456789,
      "draft": {
        "match_id": 8123456789,
        "start_time": "2026-07-14T20:30:00Z",
        "match_date": "2026-07-14",
        "patch_id": 60,
        "patch_version": "7.41",
        "radiant_team": {"team_id": 1, "name": "Radiant Pro"},
        "dire_team": {"team_id": 2, "name": "Dire Pro"},
        "ordering_quality": "authoritative",
        "completeness": "complete",
        "draft_actions": [
          {
            "source_index": 0,
            "order": 0,
            "action_type": "ban",
            "acting_side": "radiant",
            "acting_team": {"team_id": 1, "name": "Radiant Pro"},
            "hero": {"hero_id": 14, "localized_name": "Pudge"},
            "player": null
          }
        ]
      }
    }
  ]
}
```

The batch and successful items have no generic status. A successful item contains `match_id` and `draft` and omits `error`. A failed item contains `match_id` and a non-empty `error`, omits `draft`, and places its outcome in `error.status`: `unavailable`, `not_professional`, `not_parsed`, or `upstream_error`. This preserves usable neighbors without null placeholders. Diagnostic properties are optional in the generated schema and omitted from serialized output when empty.

### Optional groups

- `competition`: adds `competition: {league_id, league_name, series_id, series_type}` to each successful draft.
- `result`: adds `result: {winner, radiant_score, dire_score, duration_seconds}`.
- `draft_timing`: adds `timing: {extra_time_seconds, total_time_taken_seconds}` to each action; absent/ambiguous timing is null with a non-empty action warning.
- `provenance`: adds `provenance: {retrieved_at, source, parse_version, upstream_match_version}` and adds `warnings` there only when non-empty. `source` identifies OpenDota without exposing a credential-bearing URL.

## `list_pro_tournament_matches`

Use to resolve a professional tournament/league and retrieve a bounded newest-first match page.

### Input

| Parameter | Type | Required | Contract |
|---|---|---|---|
| `league_id` | integer or null | first page selector | Positive; mutually exclusive with `tournament_name` |
| `tournament_name` | string or null | first page selector | Nonblank normalized exact/substring query |
| `page_size` | integer or null | no | First-page default 20, range 1–100 |
| `continuation_token` | string or null | continuation only | Opaque token; may be supplied alone |

Exactly one selector is required without a token. If selector/page-size fields accompany a token they must match the snapshot. Name ambiguity returns:

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

### Success output

```json
{
  "league": {"league_id": 17272, "name": "DreamLeague Season 30", "tier": "premium"},
  "matches": [
    {
      "match_id": 8123456789,
      "start_time": "2026-07-14T20:30:00Z",
      "league": {"league_id": 17272, "name": "DreamLeague Season 30", "tier": "premium"},
      "radiant_team": {"team_id": 1, "name": "Radiant Pro"},
      "dire_team": {"team_id": 2, "name": "Dire Pro"},
      "winner": "radiant",
      "radiant_score": 31,
      "dire_score": 22
    }
  ],
  "page": {
    "returned_count": 1,
    "page_size": 20,
    "continuation_token": null,
    "terminal": true,
    "snapshot_expires_at": null
  }
}
```

A valid professional league with no eligible matches returns `matches: []`, count 0, terminal true. Amateur/ineligible leagues return a structured `ineligible_league` error.

## `list_pro_team_matches`

Use to resolve a professional team and retrieve a bounded newest-first page with optional UTC date, side, and team-relative result filters.

### Input

| Parameter | Type | Required | Contract |
|---|---|---|---|
| `team_id` | integer or null | first page selector | Positive; mutually exclusive with `team_name` |
| `team_name` | string or null | first page selector | Nonblank name/tag query |
| `start_date` | string or null | no | Inclusive UTC `YYYY-MM-DD` |
| `end_date` | string or null | no | Inclusive UTC `YYYY-MM-DD`; not before start |
| `side` | enum or null | no | `radiant` or `dire` |
| `result` | enum or null | no | Team-relative `win` or `loss` |
| `page_size` | integer or null | no | First-page default 20, range 1–100 |
| `continuation_token` | string or null | continuation only | Opaque token; may be supplied alone |

All filters combine with AND semantics. Name ambiguity returns at most 10 candidates with `team_id`, `name`, `tag`, and `last_match_time`.

### Success output

```json
{
  "team": {"team_id": 1, "name": "Radiant Pro", "tag": "RAD"},
  "filters": {"start_date": null, "end_date": null, "side": "radiant", "result": "win"},
  "matches": [
    {
      "match_id": 8123456789,
      "start_time": "2026-07-14T20:30:00Z",
      "league": {"league_id": 17272, "name": "DreamLeague Season 30", "tier": null},
      "selected_team": {"team_id": 1, "name": "Radiant Pro", "tag": "RAD"},
      "opponent": {"team_id": 2, "name": "Dire Pro", "tag": null},
      "selected_team_side": "radiant",
      "selected_team_result": "win",
      "radiant_score": 31,
      "dire_score": 22
    }
  ],
  "page": {
    "returned_count": 1,
    "page_size": 20,
    "continuation_token": null,
    "terminal": true,
    "snapshot_expires_at": null
  }
}
```

Valid filters with no records return an empty terminal page. Records where the team cannot be placed on exactly one side are excluded with a collection warning.

## Continuation rules

- The first page snapshots the complete eligible result set before slicing.
- Tokens are opaque, tool/query-bound, single-use, and expire 30 minutes after snapshot creation.
- New matches never enter an existing snapshot. Restart without a token to observe them.
- Each nonterminal response supplies the only valid next token. Replayed, malformed, expired, cross-tool, or mismatched tokens return an actionable error and no misleading page.
- Tournament traversal has no fixed total-match ceiling; only each page and the number of concurrent local snapshots are bounded.

## Errors

Expected failures use the sparse diagnostic envelope documented in [response-schemas.md](response-schemas.md): there is no root status, and the non-OK status is nested inside the emitted warning/error. Framework-level JSON-schema violations may use standard MCP invalid-arguments errors; domain validation and upstream failures use the structured diagnostic.
