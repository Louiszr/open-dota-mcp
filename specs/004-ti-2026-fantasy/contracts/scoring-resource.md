# MCP Resource Contract: TI 2026 Fantasy Scoring

## Registration

| Property | Value |
|---|---|
| URI | `opendota://fantasy/ti-2026/scoring` |
| Name | `ti_2026_fantasy_scoring` |
| MIME type | `application/json` |
| Behavior | static, read-only, idempotent, no network access |
| Content edition | `ti-2026-v1` initially; explicit inside JSON |

The server loads the installed package resource, not a cwd-relative file. Listing and reading the
resource must work through in-memory FastMCP and stdio clients.

## JSON shape

```json
{
  "edition": "ti-2026-v1",
  "competition": "The International 2026",
  "effective_date": null,
  "retrieved_at": "2026-08-01",
  "raw_score_definition": "Per-player, per-map score before quality, trait, and title modifiers.",
  "emblems": [],
  "quality_tiers": [],
  "traits": [],
  "titles": [],
  "aggregation": {},
  "sources": [],
  "caveats": []
}
```

### Emblems

Exactly 18 records cover Kills, Deaths, Creep Score, GPM, Madstone, Tower Kills, Wards Placed,
Camps Stacked, Runes Grabbed, Watchers Taken, Lotuses Grabbed, Smokes Used, Roshan Kills,
Teamfight Participation, Stuns, Tormentor Kills, Courier Kills, and First Blood. Each has:

- stable `key`, `display_name`, and `color`;
- ordered raw `inputs`, unit, and exact statistic semantics;
- typed `operation` and numeric parameters plus a human-readable formula;
- evidence `status`, `source_ids`, and concise `caveat`.

Operation values are limited to `multiply`, `sum_multiply`, `death_floor`, and `boolean_award`.
The JSON does not contain an executable expression language.

### Quality tiers

Exactly five records define I `1.10`, II `1.30`, III `1.60`, IV `2.00`, and V `2.50`. The resource
states these apply after raw score and before additional modifiers unless a source-verified rule
overrides ordering.

### Traits and titles

Every represented fact contains scope, prerequisites, stacking/order, nullable numeric effect,
status (`official`, `community_verified`, or `unknown`), sources, and caveat. Validation rejects a
numeric modifier on an `unknown` fact. Absence of adequate evidence is represented, not guessed.

The complete known trait/title name inventory and every supportable rule claim are collected and
evidence-classified during planning, before `/speckit-tasks`. Implementation does not perform rule
research: it serializes that frozen inventory into installed JSON, adds schema/source/parity tests,
and preserves unresolved effects as null with `unknown` status. Later evidence changes the edition
and retrieval metadata instead of silently mutating an existing fact.

The initial inventory is frozen as follows:

- traits: `Fractal`, `Friendly`, `Vampiric`, `Unique`, and `Benevolent`;
- title prefixes: `Otherworldly`, `Emerald`, `Golden`, `Heroic`, `Cerulean`, `Royal`, `Crimson`,
  and `Elemental`;
- title suffixes: `the Tormented`, `the Flayed Twins Acolyte`, `the Patient`, `the Underdog`,
  `the Decisive`, `the Clutch`, `the Lucky`, and `the Cruel`.

Title records carry `component` (`prefix` or `suffix`). The current community guide supports a
`+30%` claim for `Unique` and `+6%` for `the Underdog`; both are
`community_verified`, not official. Its percentages beside player/prefix names are observed match
eligibility rates, not modifier values, and must not populate `numeric_effect`. Exact mechanics or
amounts absent from adequate evidence remain null and `unknown`, including the other initial
inventory records.

### Aggregation

The resource defines:

1. Both selected Core players contribute additively to their shared banner, as do both Support
   players, with evidence status and caveat.
2. For each player and confirmed series, select up to the two highest-scoring maps and sum them.
3. The player's stage contribution is the greatest confirmed-series sum.
4. Maps with null series IDs remain visible evidence but cannot be grouped or declared the best
   series without additional verified identity.

## Source records and versioning

Each source has stable ID, title, URL, publisher/type, retrieval date, and optional note. Supplied
feature formulas are identified as baseline product inputs rather than silently labeled official.
Updating any rule requires a new edition value and retrieval/effective metadata; the stable URI
continues to expose the current supported edition.

## Contract invariants

- Emblem keys and formula parameters exactly match the service's canonical definitions.
- Every formula input maps to a documented tool raw-stat key.
- All source references resolve within the document and direct links are nonblank HTTPS URLs.
- Unknown effects have null numeric values.
- JSON is finite, deterministic, and readable without OpenDota or web access.
