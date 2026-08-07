# MCP Tool Contract: `get_pro_player_fantasy`

The server adds one read-only, idempotent FastMCP tool. Successful and expected failure results are
typed structured JSON; timestamps use UTC ISO 8601 with `Z`.

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
| `account_id` | integer? | one selector | Positive professional Steam32 account ID |
| `player_name` | string? | one selector | Nonblank professional-name query |
| `match_count` | integer? | no | Default 20; 1-100 eligible maps after filtering |
| `version_pattern` | string? | no | Max 64; timeout-bounded full-string patch expression |
| `start_date` | string? | no | Inclusive UTC `YYYY-MM-DD` |
| `end_date` | string? | no | Inclusive UTC `YYYY-MM-DD`, not before start |
| `tournament_tiers` | string[]? | no | Default `[premium]`; named subset or only `all` |
| `include` | string[]? | no | Distinct subset containing only `fantasy_scoring` |

Exactly one player selector is required. A stable ID is checked against the professional catalog.
Both a name query and catalog names are normalized with Unicode NFKC, Unicode case folding,
replacement of each contiguous punctuation-or-whitespace run with one ASCII space, and trimming.
A normalized-empty query is invalid. A name auto-resolves only one normalized exact
professional-name match; otherwise the response requires explicit selection from at most 10
candidates ordered by normalized professional name then account ID.

Tier choices are `premium`, `professional`, `amateur`, and `all`. Named tiers may combine; `all` is
exclusive. Tier 1 means `premium`. Omitting `version_pattern` selects the latest valid patch by
catalog date. All active filters combine with AND semantics. Tournament tiers only narrow matches
that already passed mandatory professional-league verification. `all` means all verified league
tiers, never public matchmaking. The schema intentionally provides no public/pub-match selector,
lobby-mode selector, or professional-provenance override.

## Non-configurable professional-match eligibility

Every returned record must have affirmative professional-league provenance. The service hydrates
each candidate match and requires a positive `leagueid` that resolves to authoritative league
metadata without contradictory evidence. A resolved professional account, a parsed player row,
team IDs, or complete statistics are not substitutes for this proof. Candidates from public
matchmaking, and candidates with missing, zero, unknown, or contradictory league provenance, are
discarded before patch/date/tier filters and before `match_count` is applied. This invariant applies
to every valid request, including `tournament_tiers=["all"]`.

## Description requirements

The registered description states selector/disambiguation behavior, newest-first post-filter limit,
20 default/100 maximum, latest patch behavior, full tier choices, inclusive UTC dates, nullable
series IDs, raw-stat scope, Madstone and other unavailable-stat limitations, the
`fantasy_scoring` group, bounded history coverage, successful empty results, meaningful errors, and
that only league-verified professional matches are eligible with no option to include pubs.

## Slim response

```json
{
  "player": {"account_id": 101, "pro_name": "Example"},
  "filters": {
    "patch": "7.41",
    "start_date": "2026-07-01",
    "end_date": "2026-07-31",
    "tournament_tiers": ["premium"]
  },
  "coverage": {
    "history_records_examined": 80,
    "details_requested": 24,
    "details_usable": 22,
    "history_exhausted": false,
    "truncated": false,
    "terminal_reason": "requested_count_met"
  },
  "returned_count": 20,
  "matches": [
    {
      "context": {
        "match_id": 8123456789,
        "start_time": "2026-07-14T20:30:00Z",
        "patch": "7.41",
        "tournament_name": "The International 2026",
        "tournament_tier": "premium",
        "series_id": 5001,
        "player": {"account_id": 101, "pro_name": "Example"},
        "team": {"team_id": 1, "name": "Radiant Pro"},
        "opponent": {"team_id": 2, "name": "Dire Pro"},
        "hero": {"hero_id": 25, "name": "Lina"},
        "result": "win",
        "duration_seconds": 2216,
        "team_kills": 31,
        "opponent_kills": 22
      },
      "raw_stats": {
        "kills": 8,
        "deaths": 2,
        "assists": 14,
        "last_hits": 312,
        "denies": 18,
        "gold_per_minute": 668,
        "madstones_collected": null,
        "tower_last_hits": 2,
        "observer_wards_placed": 1,
        "camps_stacked": 3,
        "runes_picked_up_or_bottled": 5,
        "watchers_captured": null,
        "lotuses_taken": null,
        "smoke_of_deceit_uses": 0,
        "roshan_last_hits": 0,
        "teamfight_participation": 0.7096774194,
        "stun_duration_seconds": 42.75,
        "tormentor_last_hits": 1,
        "courier_last_hits": 0,
        "first_blood": false
      }
    }
  ],
  "warnings": [
    {
      "code": "madstone_unavailable",
      "message": "OpenDota does not expose a verified per-player Madstones-collected total. item_uses.madstone_bundle counts item-use events, not collection, so this contribution cannot be calculated."
    },
    {
      "code": "watchers_unavailable",
      "message": "OpenDota ability_uses.ability_lamp_use combines neutral and enemy Watcher captures and exposes no target-state detail, so exact fantasy Watchers Taken cannot be calculated."
    },
    {
      "code": "lotuses_unavailable",
      "message": "OpenDota exposes no compatible per-player lotus collection field or pickup event. Lotus item-use counters describe consumption, not collection, so this contribution cannot be calculated."
    }
  ]
}
```

Required raw keys remain present with null. Missing optional context uses null; it does not become a
reason/status wrapper. The root emits one deduplicated warning for each unavailable scoring
statistic represented in the returned maps. Warnings are sparse and never contain secrets or raw
bodies.

`tormentor_last_hits` is derived from attributed `CHAT_MESSAGE_MINIBOSS_KILL` objective events, not
from team totals. A complete applicable objective ledger with no event credited to the selected
player yields `0`; missing objective evidence, a pre-Tormentor patch, or any Tormentor event without
a unique and team-consistent `player_slot` yields null.

## `fantasy_scoring` group

When requested, the root adds
`"reference_uri":"opendota://fantasy/ti-2026/scoring"` and each map adds exactly 18 entries:

```json
{
  "fantasy_scoring": {
    "emblems": [
      {
        "key": "kills",
        "color": "red",
        "inputs": {"kills": 8},
        "raw_points": 856
      },
      {
        "key": "madstone",
        "color": "red",
        "inputs": {"madstones_collected": null},
        "raw_points": null
      }
    ]
  }
}
```

Entries carry only observed calculation evidence and pre-modifier raw points. The resource defines
formulas, tiers, traits, titles, banner rules, sources, aggregation, and retrospective application
semantics. An agent may combine those rules with a candidate configuration to calculate a
counterfactual projection, but no quality, trait, title, banner, loadout, or projected post-modifier
value is represented as historical match data.

## Resolution, empty, partial, and error outcomes

- Ambiguous or non-exact names return `needs_selection` plus at most 10 candidates and no match
  reads. Blank/no-match/direct-nonprofessional inputs return structured identity errors.
- A valid exhaustive request with no eligible maps succeeds with `matches=[]` and count zero.
- Missing optional per-map data preserves the map and produces null plus a focused warning.
- Player history is read in pages of at most 100 records. A request examines at most 500 history
  records and hydrates at most 200 unique match details. Reaching either fixed internal limit returns
  verified maps, examined/hydrated counts, `truncated=true`, a limit-specific terminal reason, and a
  warning that more eligible maps may exist; it does not claim the list is exhaustive.
- Invalid selectors, limits, dates, patterns, tier combinations, or include values fail before
  detail fan-out. `invalid_include` reports `valid_values:["fantasy_scoring"]`.
- Safe retry exhaustion returns an actionable sanitized error. Cancellation propagates. A failed
  record may be skipped with a warning when other maps remain trustworthy.

## Ordering and compatibility

Eligible maps sort by `start_time` descending, then match ID descending; the public limit is applied
last. Existing four tools keep names and schemas. Together with `get_pro_team_roster`, the server
now lists six tools and one resource.
No arbitrary OpenDota fields, timelines, loadouts, or inferred series appear in this contract.
