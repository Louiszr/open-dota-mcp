# MCP Tool Contract: `get_pro_team_roster`

The server adds a focused read-only, idempotent FastMCP tool that bridges a professional team to
fantasy-ready player account IDs. “Roster” means the latest observed parsed lineup cross-checked
against OpenDota's explicit current-member records; it is not an authoritative roster registry.

## Annotations

```json
{
  "readOnlyHint": true,
  "destructiveHint": false,
  "idempotentHint": true,
  "openWorldHint": true
}
```

## Input

| Parameter | Type | Required | Contract |
|---|---|---|---|
| `team_id` | integer? | one selector | Positive stable professional-team ID |
| `team_name` | string? | one selector | Nonblank normalized team name or tag |

Exactly one selector is required. A unique normalized exact name/tag may resolve automatically;
ambiguous matches return at most 10 compact team candidates and require `team_id`. The scan bound
is intentionally fixed and has no pagination, count, include, patch, tier, or date parameter.

## Selection and cross-check algorithm

1. Resolve the team and load its team-player response plus match history through the safe cache and
   retry boundary.
2. Require exactly five distinct positive team-player account IDs with
   `is_current_team_member=true`. Null and false do not count. Otherwise return
   `current_roster_unavailable` without inspecting positions.
3. Normalize completed matches newest first and consider at most five. Hydrate sequentially. Move
   past a record only when it is unparsed or cannot establish one verified team side with exactly
   five distinct positive account IDs.
4. On the first usable match, compare its five-ID set with the five current-member IDs. If they do
   not match, return `lineup_mismatch` immediately and do not search older records or infer players.
5. If the sets match, map lane and ten-minute farm evidence and return exactly five players.

## Successful response

```json
{
  "team": {"team_id": 1, "name": "Radiant Pro"},
  "source_match": {
    "match_id": 8123456789,
    "start_time": "2026-07-14T20:30:00Z"
  },
  "coverage": {
    "completed_records_considered": 2,
    "details_requested": 2,
    "parsed_usable": 1
  },
  "players": [
    {
      "account_id": 101,
      "pro_name": "Carry",
      "position": 1,
      "lane": "safelane",
      "last_hits_at_10": 82,
      "inference_status": "inferred"
    },
    {
      "account_id": 105,
      "pro_name": "Support",
      "position": 5,
      "lane": "safelane",
      "last_hits_at_10": 12,
      "inference_status": "inferred"
    }
  ]
}
```

`players` contains five records. Ordering is position ascending when all positions are known;
otherwise known positions sort first and ambiguous players sort by account ID. Names may be null.

## Position inference

The only complete inference shape is two safelane, one midlane, and two offlane players. The unique
midlane player is position 2. Within safelane, distinct last-hit samples at or before 10:00 map the
higher value to position 1 and lower to position 5. Within offlane, they map to positions 3 and 4.

Missing/tied samples, invalid lane roles, roaming/trilane distributions, or malformed series never
fall back to player slot, catalog `fantasy_role`, hero, final farm, or history. Supported positions
may remain present while only affected positions are null; each null record has
`inference_status="ambiguous"` and one root warning summarizes the evidence gap.

## Cannot-infer and error outcomes

- `current_roster_unavailable`: the team-player endpoint does not establish exactly five distinct
  explicitly current member IDs. No players or positions are returned.
- `lineup_mismatch`: the newest usable parsed match's five IDs differ from the current-member set,
  suggesting a stand-in or roster change. Return resolved team, source match, coverage, and the
  concise error only; do not expose inferred players and do not search older matches.
- `lineup_unavailable`: none of the newest five completed records is a usable parsed five-player
  team lineup. Return resolved team, coverage, and retry/investigation guidance.
- Team ambiguity returns `needs_selection` with at most 10 candidates and performs no match-detail
  reads. Invalid/not-found selectors and sanitized upstream exhaustion use existing structured
  errors. Cancellation propagates.

## Description requirements and compatibility

The registered description states selector behavior, the fixed newest-plus-four scan, parsed-map
requirement, exact current-member cross-check, stand-in/roster-change mismatch behavior, nullable
match-derived positions, source-match provenance, and meaningful errors. Existing four tools keep
their schemas; with `get_pro_player_fantasy`, the server lists six tools and one resource.
