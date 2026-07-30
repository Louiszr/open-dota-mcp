# MCP Tool Contract: `analyze_pro_team_drafts`

The server adds one read-only, idempotent FastMCP tool. It accepts a stable team ID; callers needing
name resolution use the existing team lookup capability. Successful and expected failure results
are typed structured JSON. Timestamps are UTC ISO 8601 strings with `Z`.

## Tool annotations

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
| `team_id` | integer? | first page | Positive professional team ID; names are invalid |
| `lookback_count` | integer? | no | Default 25; 1-100 completed matches before filters |
| `version_pattern` | string? | no | Max 64 chars; timeout-bounded full-string regex over patch labels |
| `tournament_tiers` | string[]? | no | Default `[premium]`; named subset or only `all` |
| `side` | string? | no | `radiant` or `dire`, team relative |
| `result` | string? | no | `win` or `loss`, team relative |
| `first_ban` | string? | no | `yes` or `no`, team relative |
| `include` | string[]? | no | Distinct subset of `draft`, `lanes`, `economy`, `structures`, `objectives` |
| `page_size` | integer? | no | Default 10; 1-25 eligible matches |
| `continuation_cursor` | string? | continuation | Opaque rotating cursor |

Without a cursor, `team_id` is required and all arguments are validated before match-detail reads.
With a cursor, no other argument is necessary. Repeated first-page arguments must fingerprint to the
saved request.

Tier choices are `premium`, `professional`, `amateur`, and `all`. Named tiers may be combined;
`all` is mutually exclusive. The default `[premium]` is Tier 1.

When `version_pattern` is omitted, the latest valid catalog patch by release date supplies the
exact patch label. A caller pattern replaces that default and uses full-string semantics.

## Tool description requirements

The registered description tells an agent:

- the 25 default/100 maximum completed-match quota is consumed before parsing and filters;
- Tier 1 means `premium`, with all four tier values and combination rules;
- omitted patch expression means the latest dated catalog label;
- side, result, and first-ban filters are team relative and combine with AND;
- the default is a lean match core plus aggregate parse coverage;
- five additive evidence groups are available;
- pages default to 10 and allow at most 25 eligible matches;
- sparse `null`/omitted fields can occur; and
- upstream retry exhaustion is bounded.

## Lean default response

Only eligible parsed matches are paged. Unparsed, filtered, malformed, and failed-detail matches
contribute to `coverage` but are not expanded into public outcomes.

```json
{
  "team": {"team_id": 1, "name": "Radiant Pro"},
  "filters": {
    "patch": "7.41",
    "tournament_tiers": ["premium"]
  },
  "coverage": {
    "examined": 25,
    "parsed": 20,
    "unparsed": 5
  },
  "matches": [
    {
      "match_id": 8123456789,
      "start_time": "2026-07-14T20:30:00Z",
      "duration_seconds": 2216,
      "tournament": {"name": "Premier Cup", "tier": "premium"},
      "patch": "7.41",
      "analyzed_team": "Radiant Pro",
      "opponent": {"team_id": 2, "name": "Dire Pro"},
      "side": "radiant",
      "result": "win",
      "ban_order": "first"
    }
  ],
  "next_cursor": "opaque-rotating-value"
}
```

The response deliberately omits team tags, league/patch/hero/account IDs, request echoes, catalog
metadata, valid-value lists, filter evaluations, exclusion maps, per-stage coverage, provenance,
source fields, availability/quality/completeness wrappers, warning arrays, returned counts,
terminal flags, and snapshot expiry. `next_cursor` is omitted on the last page.

## `draft` group

Adds one chronological action list to each eligible match:

```json
{
  "actions": [
    {
      "order": 0,
      "type": "ban",
      "round": 1,
      "team": "Radiant Pro",
      "hero": "Pudge"
    },
    {
      "order": 4,
      "type": "pick",
      "round": 1,
      "team": "Radiant Pro",
      "hero": "Lina",
      "player": "MidPlayer",
      "matchup": {
        "known": true,
        "lane": "midlane",
        "opposing_heroes": ["Storm Spirit"]
      }
    }
  ]
}
```

`type` is the phase. `round` is reconstructed per team: take that team's actions in global order,
group consecutive equal types, and number ban runs and pick runs independently from 1. Both teams
therefore have their own ban round 1 and pick round 1. If ordering is ambiguous, `round` is omitted.
`player` and `matchup` are likewise omitted when they cannot be established. Hero references are
always localized-name strings, never structs.

For example, one team's type subsequence `ban, ban, pick, pick, ban, pick` receives rounds
`1, 1, 1, 1, 2, 2` respectively; the action type distinguishes ban round 1 from pick round 1.

## `lanes` group

Adds analyzed-team-perspective lane comparisons:

```json
{
  "lanes": [
    {
      "lane": "midlane",
      "analyzed_team_heroes": ["Lina"],
      "opponent_heroes": ["Storm Spirit"],
      "experience_difference_10": 320,
      "last_hit_difference_10": 8
    }
  ]
}
```

Missing comparisons are `null`.

## `economy` group

Adds supported gold facts only:

```json
{
  "gold_difference_10": 1450,
  "gold_difference_20": -320,
  "hero_total_gold": [
    {
      "hero": "Lina",
      "player": "MidPlayer",
      "team": "Radiant Pro",
      "at_10": 4720,
      "at_20": 10110
    }
  ]
}
```

The checkpoint values are from the analyzed-team perspective and latest observation at or before
the named minute. `hero_total_gold` is sourced from OpenDota's `gold_t`; it is not labeled exact
net worth.

## `structures` group

Adds cumulative compact structure-key lists:

```json
{
  "analyzed_team_lost": {
    "by_10": ["top_t1"],
    "by_20": ["top_t1", "mid_t1"]
  },
  "opponent_lost": {
    "by_10": [],
    "by_20": ["bottom_t1"]
  }
}
```

`[]` means verified none and `null` means the checkpoint could not be established. The compact
keys cover lane/tier towers, melee/ranged barracks, and tier 4 towers without zero-filled trees or
redundant totals.

## `objectives` group

Adds attributable event-time lists through 25 minutes:

```json
{
  "analyzed_team": {
    "roshan_by_25": [],
    "tormentor_by_25": [1477]
  },
  "opponent": {
    "roshan_by_25": [],
    "tormentor_by_25": []
  }
}
```

`[]` means verified zero and `null` means unavailable or not applicable. Counts and first-take
times are derivable and therefore omitted.

## Empty result and continuation

A valid request with no eligible matches returns `matches=[]`, compact coverage, and no cursor.
Selection and requested groups are materialized before the first page is sliced. A valid cursor
performs no OpenDota request, remains tool/query-bound and single-use, and preserves the snapshot's
order and coverage. Invalid or expired cursors return concise restart guidance.

## Compatibility

The three existing tools retain their names and schemas. The server exposes four read-only tools.
Raw OpenDota fields never enter this contract merely because upstream adds them.
