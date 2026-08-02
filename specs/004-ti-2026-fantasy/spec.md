# Feature Specification: TI 2026 Fantasy Analysis

**Feature Branch**: `004-ti-2026-fantasy`

**Created**: 2026-08-01

**Status**: Draft

**Input**: User description: "Create agent-oriented tools and reference context for evaluating TI 2026 fantasy players from recent professional-match performance, match context, series grouping, emblem scoring, quality tiers, traits, and titles."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review a Player's Fantasy Evidence (Priority: P1)

An analysis agent identifies a professional player and requests that player's newest eligible professional maps. It receives compact per-map raw fantasy statistics plus hero, opponent, result, score, duration, patch, tournament, and nullable series identity so it can judge whether a proposed emblem combination suits the player's actual performance.

**Why this priority**: Map-level player evidence is the core input needed to replace blind reroll optimization with player-specific fantasy decisions.

**Independent Test**: Request recent maps for a known player across fixtures containing several patches, tournament tiers, date ranges, opponents, heroes, and series; verify that every returned map satisfies the filters and contains the defined fantasy statistics and context without unrelated match-detail fields.

**Acceptance Scenarios**:

1. **Given** a known professional player with complete parsed matches, **When** an agent requests the latest 20 eligible maps, **Then** the response returns up to 20 maps newest first with all available raw fantasy statistics and required match context.
2. **Given** patch, inclusive UTC date, and tournament-tier filters, **When** the agent requests the player's maps, **Then** only maps satisfying every supplied filter are returned and the limit is applied after filtering.
3. **Given** consecutive maps with the same known series identity, **When** they are returned, **Then** they expose the same series ID; maps without reliable series metadata remain in the result with a null series ID.
4. **Given** a map with unavailable optional statistics, **When** it is returned, **Then** unavailable values are null rather than zero or inferred, while usable maps remain in the response.
5. **Given** Madstone collection is unavailable from the supported match source, **When** any result is returned, **Then** every map retains `madstones_collected` as null and the response warns once that this statistic is unavailable.
6. **Given** the resolved professional player's history contains public matchmaking games, including games that satisfy every requested patch/date/tier-independent condition, **When** the capability collects evidence with any supported tournament-tier selection including `all`, **Then** every public game is excluded before the result limit is applied and no request option can include it.

---

### User Story 2 - Understand TI 2026 Scoring and Modifiers (Priority: P2)

An MCP client loads a compact TI 2026 fantasy reference that explains every emblem's base formula, quality-tier multiplier, known trait and title effects, stage aggregation rules, provenance, and confidence or uncertainty without searching the web during analysis.

**Why this priority**: Raw performance evidence cannot support lineup decisions unless the client can consistently translate it into the current competition's scoring system and account for modifiers.

**Independent Test**: Load the reference and verify that it fully represents the supplied 18-emblem scoring table, five quality tiers, teamfight-participation interpretation, series/stage aggregation, known trait/title rules, and explicit unknown or community-verified qualifications.

**Acceptance Scenarios**:

1. **Given** a client that has not loaded any fantasy rules, **When** it reads the TI 2026 reference, **Then** it can calculate every available raw emblem score and apply each of the five base quality multipliers without outside context.
2. **Given** a rule that is community-verified rather than formally documented by Valve, **When** the reference presents it, **Then** the rule is labeled with its evidence status and direct source attribution.
3. **Given** a trait or title whose exact effect cannot be verified, **When** the reference is loaded, **Then** the effect is marked unknown or unavailable and is not guessed.
4. **Given** a scoring rule changes or new evidence becomes available, **When** the reference is updated, **Then** clients can identify its edition and effective/retrieval date rather than silently mixing rule sets.

---

### User Story 3 - Evaluate Stat Combinations in Series Context (Priority: P3)

An analysis agent combines recent-map evidence with the scoring reference to compare whether a set of emblems, quality tiers, traits, and titles complements a player's repeatable strengths, including the rule that only the two best maps from the player's best series count for a stage.

**Why this priority**: The desired advantage comes from composition fit and series consistency, not merely selecting individually high-looking rerolls.

**Independent Test**: Use returned maps spanning known and unknown series IDs to calculate candidate emblem outcomes, verify known series grouping, and confirm that missing series metadata is preserved as uncertainty rather than assigned to a fabricated series.

**Acceptance Scenarios**:

1. **Given** at least two known series for a player, **When** an agent evaluates a candidate emblem set, **Then** the response and reference provide enough evidence to identify the two highest-scoring maps in each series and compare the best series.
2. **Given** a mixture of known-series and unknown-series maps, **When** the agent analyzes consistency, **Then** all maps remain available and unknown-series maps are clearly distinguishable from confirmed groups.
3. **Given** match-bound modifier information is available from a verified source, **When** a map is returned, **Then** that information is included with its value and provenance; otherwise modifier fields are null or omitted according to the documented response group and are never inferred from performance.

### User Story 4 - Resolve a Team's Latest Observed Lineup (Priority: P1)

An analysis agent starts with a professional team and requests a compact latest-observed lineup. It
receives the five stable player account IDs from the team's newest usable parsed professional map,
plus match-derived positions where lane and early-farm evidence supports a deterministic inference,
so it can call the player-fantasy capability without separately resolving every player name.

**Why this priority**: The fantasy capability requires player IDs, while the common workflow begins
with a team. A focused bridge prevents name ambiguity and avoids making the agent inspect a large
draft-analysis response merely to recover five IDs.

**Independent Test**: Supply team histories whose newest records include unparsed, malformed, and
usable parsed maps; verify that no more than five records are inspected, the newest usable
five-player lineup is selected, its account-ID set exactly matches the current-member set from the
team-player endpoint, clean 2-1-2 lane evidence maps to positions 1-5, and any membership mismatch
returns a cannot-infer outcome.

**Acceptance Scenarios**:

1. **Given** a stable professional team ID whose newest completed map is parsed and contains five distinct account IDs, **When** an agent requests the lineup, **Then** the response returns those five IDs and the source match ID in one bounded call.
2. **Given** a clean 2-1-2 lane assignment with distinct ten-minute last-hit values within each side lane, **When** positions are inferred, **Then** safelane players map to positions 1 and 5, the unique mid player maps to position 2, and offlane players map to positions 3 and 4.
3. **Given** missing lane roles, missing or tied ten-minute last hits, roaming/trilane evidence, or fewer/more than five distinct team players, **When** the lineup is evaluated, **Then** no unsupported position is invented and the response returns nullable positions or a focused unusable-lineup outcome.
4. **Given** the newest completed team match is unparsed, **When** a bounded later record is usable, **Then** that newest usable parsed match supplies the lineup and coverage reports how many records were examined.
5. **Given** the selected match contains a stand-in or reflects a roster that differs from the team endpoint's five current members, **When** the membership sets are compared, **Then** the capability returns `lineup_mismatch` without inferring positions or searching older matches.

### Edge Cases

- A player name is blank, reused, changed, or matches multiple professionals: reject blank input; prefer a stable account ID; return bounded candidates for ambiguous names without silently selecting one.
- A player has fewer eligible maps than requested or none at all: return every eligible map or an empty successful collection with the resolved player and applied filters.
- The lookback is outside its allowed bounds, dates are malformed/reversed, a patch expression is invalid, or tiers are contradictory: reject the request with valid correction choices.
- A match is unparsed or lacks a player row, patch, tournament tier, opponent, hero, score, or series metadata: do not invent data; exclude a match only when an active filter cannot be evaluated, otherwise retain it with null fields and focused warnings.
- A series ID is absent, inconsistent, or reused across unrelated competitions: preserve a trustworthy upstream value only; null is preferable to inferred grouping.
- A match is abandoned, incomplete, or has no determinable winner: exclude it from completed-map results and do not consume the returned-result limit.
- A professional player's history contains a complete parsed public match, or a match lacks affirmative professional-league provenance: exclude it regardless of all other filters; player identity, parse completeness, team IDs, or `tournament_tiers=[all]` MUST NOT make it eligible.
- The player's team has zero kills: return a null teamfight-participation ratio and raw score with a warning rather than dividing by zero.
- A count is legitimately zero: preserve zero and do not treat it as unavailable.
- First Blood attribution is missing: return null; return false only when the data establishes that another player received First Blood.
- A stat label has narrower scoring semantics than a similarly named upstream value, such as observer wards rather than all wards: use only evidence matching the scoring definition and mark the value unavailable if it cannot be distinguished.
- The upstream service throttles, times out, returns malformed data, or partially fails: use bounded safe recovery, retain otherwise usable maps, and surface actionable exhaustion or record-level warnings.
- A team's latest completed match is unparsed or lacks exactly five distinct positive account IDs: continue through at most four older completed matches; if none is usable, return an actionable lineup-unavailable outcome.
- A parsed lineup has duplicate account IDs, unexpected player slots, missing lane roles, a non-2-1-2 lane distribution, missing ten-minute last-hit samples, or tied farm evidence: preserve trustworthy player IDs but leave affected positions null rather than guessing.
- A player's current catalog team or `fantasy_role` conflicts with the selected match: the selected match establishes observed participation; catalog role data does not override match-derived position evidence.
- The team-player endpoint does not identify exactly five distinct `is_current_team_member=true` account IDs, or those IDs differ from the newest usable parsed lineup: return a cannot-infer outcome; do not search an older match to hide a stand-in or roster change.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST expose one focused read-only player-fantasy capability that accepts a stable professional-player account ID or a professional-name query and returns recent completed professional maps for the resolved player.
- **FR-002**: Name matching MUST be case-insensitive and normalize harmless punctuation and spacing differences. It MUST prefer a unique normalized exact professional-name match; otherwise it MUST return at most 10 concise candidates with stable account IDs and require explicit selection.
- **FR-003**: The capability MUST accept a requested match count from 1 through 100, defaulting to 20. It MUST apply the count after all filters and return maps newest first. Because the caller requests a finite bounded collection, pagination is not required for this capability.
- **FR-004**: The capability MUST support the same fantasy-analysis filter semantics as the existing professional draft-analysis capability: an optional patch-version expression, inclusive `start_date` and `end_date` in `YYYY-MM-DD` UTC form, and a non-empty tournament-tier list containing distinct `premium`, `professional`, and `amateur` values or the single mutually exclusive value `all`.
- **FR-005**: Unless overridden, the patch filter MUST resolve to the latest dated patch in the available patch catalog and the tournament-tier filter MUST default to `[premium]`, presented as Tier 1. All filters MUST combine with AND semantics.
- **FR-006**: Each map's compact context MUST include match ID, UTC start time, patch label, tournament name and raw tier, series ID or null, player account ID and professional name, player's team ID/name, opponent team ID/name, hero ID/name, team-relative win/loss result, duration in seconds, player's team kill score, and opponent kill score.
- **FR-007**: A missing series ID MUST NOT exclude an otherwise eligible map, and the server MUST NOT infer a series from time proximity, opponent, tournament, or best-of format.
- **FR-008**: Each map MUST include the raw inputs needed for TI 2026 emblem analysis: kills, deaths, assists, last hits, denies, GPM, Madstones collected, tower last-hits, observer wards placed, camps stacked, runes picked up or bottled, Watchers captured, lotuses taken, Smoke of Deceit uses, Roshan last-hits, teamfight-participation ratio, accumulated stun duration in fractional seconds, Tormentor last-hits, courier last-hits, and First Blood attribution.
- **FR-009**: Statistical fields MUST distinguish zero, false, and unavailable values. Unavailable values MUST be null and MUST NOT be estimated from unrelated measures.
- **FR-010**: `madstones_collected` MUST remain present and null on every map until a verified supported source exists. The response MUST contain one concise warning explaining that Madstone data is unavailable and therefore its fantasy contribution cannot be calculated.
- **FR-011**: Teamfight participation MUST represent `(player kills + player assists) / player's team kills` for nonzero team kills, with a range of 0 through 1. The value and corresponding fantasy points MUST be null when the team kill denominator is zero or the required inputs are unavailable.
- **FR-012**: Accumulated stun duration MUST permit fractional seconds and cover hero and non-hero units when the source supports that definition. First Blood MUST be true only for the credited player, false only when another player is reliably credited, and null when attribution is unavailable.
- **FR-013**: The default response MUST remain bounded to player identity, applied filter summary, compact match context, raw fantasy-stat fields, sparse warnings, and collection count; it MUST NOT expose arbitrary upstream match records or unrelated timeline data.
- **FR-014**: The capability MUST support an additive `fantasy_scoring` response group that supplies, for every emblem statistic, its TI 2026 color, base formula inputs, computed raw points when all inputs are available, and null otherwise. Invalid field-group selections MUST be rejected with the valid choices.
- **FR-015**: The `fantasy_scoring` group MUST implement these per-player, per-map raw formulas before quality, traits, and titles: Kills `107 × kills`; Deaths `max(0, 1950 − 195 × deaths)`; Creep Score `3 × (last hits + denies)`; GPM `2 × GPM`; Madstone `13 × collected`; Tower Kills `352 × tower last-hits`; Wards Placed `117 × observer wards placed`; Camps Stacked `234 × camps`; Runes Grabbed `141 × runes`; Watchers Taken `147 × watchers`; Lotuses Grabbed `176 × lotuses`; Smokes Used `293 × smokes`; Roshan Kills `1172 × Roshan last-hits`; Teamfight Participation `2124 × participation`; Stuns `10 × stun seconds`; Tormentor Kills `879 × Tormentor last-hits`; Courier Kills `703 × courier last-hits`; and First Blood `1934` when true and `0` when reliably false.
- **FR-016**: The server MUST expose a compact, client-readable TI 2026 fantasy scoring reference as an MCP resource rather than requiring a live web search. The reference MUST have a stable address, edition identifier, effective/retrieval date, and source links.
- **FR-017**: The reference MUST define all red, blue, and green emblem metrics and formulas in FR-015, the exact raw-stat semantics in FR-008 through FR-012, and the distinction between raw score and post-modifier score.
- **FR-018**: The reference MUST define the five base emblem-quality multipliers: Tier I `1.10`, Tier II `1.30`, Tier III `1.60`, Tier IV `2.00`, and Tier V `2.50`, applied after raw score and before any additional trait or title effect unless verified rules state a different order.
- **FR-019**: The reference MUST document every verified TI 2026 trait and title effect that changes eligibility, effective percentage, aggregation, or final score, including prerequisites, stacking/order rules, numeric value when known, and whether the rule applies per emblem, player, banner, series, or stage.
- **FR-020**: Trait and title facts MUST carry a status of `official`, `community_verified`, or `unknown`, with direct source attribution and a concise caveat. An effect lacking adequate evidence MUST be represented as unknown and MUST NOT be assigned a numeric modifier.
- **FR-021**: When verified match-bound tier, trait, or title information is available, the optional scoring group MUST associate it with the affected map and identify its provenance. When no such match-bound data exists, the response MUST not imply that a player's historical map was played with a particular fantasy loadout.
- **FR-022**: The reference MUST explain that both selected Core players and both selected Support players contribute additively to their shared banner and that only the two best-scoring maps from a player's best series count for the stage, while distinguishing verified rules from assumptions.
- **FR-023**: Tool descriptions MUST state player-resolution behavior, newest-first post-filter limit semantics, default/latest patch behavior, all tournament-tier choices, inclusive UTC dates, the 20-map default and 100-map maximum, nullable series IDs, raw-stat scope, Madstone limitation, available response groups, and meaningful error outcomes.
- **FR-024**: Valid requests with no matching maps MUST return an empty successful collection. Invalid identities, filters, limits, or response groups MUST return concise structured errors; per-map missing data MUST not fail otherwise usable results.
- **FR-025**: Safe upstream reads MUST absorb eligible intermittent throttling, timeouts, connection failures, and server failures using finite retry behavior that respects upstream retry instructions, caller cancellation, and caller deadlines. Exhaustion MUST return an actionable error without leaking secrets.
- **FR-026**: Public access without an API key MUST remain supported where the match source permits it. Any optional configured key MUST remain secret; OAuth and write operations are out of scope.
- **FR-027**: The player-fantasy capability and scoring reference MUST have deterministic offline-capable coverage for complete data, legitimate zeroes, nulls, Madstone warnings, formulas, player disambiguation, filters, bounds, series grouping/non-grouping, invalid inputs, partial failures, retry recovery/exhaustion, and client discovery/readability.
- **FR-028**: The server MUST expose one focused read-only latest-lineup capability that accepts exactly one positive stable professional-team ID or normalized team name/tag selector and returns player IDs suitable for direct use with the player-fantasy capability.
- **FR-029**: Team-name resolution MUST reuse the existing bounded team-candidate behavior. A unique normalized exact name/tag match may auto-resolve; ambiguity MUST return at most 10 concise team candidates and require a stable ID.
- **FR-030**: The lineup capability MUST inspect at most the five newest completed team-history records, newest first, and select the first usable parsed match that contains exactly five distinct positive account IDs on the requested team's verified side. It MUST move to an older record only when a newer record is unparsed or otherwise inconclusive. This fixed finite search returns at most five players, so public pagination and a caller lookback control are not required.
- **FR-031**: Every successful lineup MUST include the resolved team, source match ID and UTC start time, examined/parsed coverage, exactly five compact player records, and sparse warnings. Each player record MUST include stable account ID, professional name or null, inferred position `1` through `5` or null, lane role or null, ten-minute last hits or null, and an inference status.
- **FR-032**: Position inference MUST use only the selected parsed match. For a clean 2-1-2 distribution, the unique midlane player is position 2; within safelane the higher distinct ten-minute last-hit value is position 1 and the lower is position 5; within offlane the higher value is position 3 and the lower is position 4. Missing, tied, malformed, roaming, or non-2-1-2 evidence MUST yield null for every unsupported position.
- **FR-033**: Before returning players or positions, the capability MUST load `/teams/{team_id}/players`, require exactly five distinct positive account IDs whose `is_current_team_member` value is explicitly true, and require that set to equal the five-player set from the selected parsed match. A mismatch indicates a possible stand-in or roster change and MUST return `lineup_mismatch` without inferred players or further match scanning.
- **FR-034**: The response MUST identify positions as match-derived inference and MUST NOT claim that the selected lineup or positions are an authoritative current roster. OpenDota catalog `fantasy_role`, player-slot order, final-match farm, names, and historical frequency MUST NOT substitute for the inference in FR-032.
- **FR-035**: A valid team with no usable parsed lineup in the fixed lookback MUST return a concise `lineup_unavailable` error with examined/parsed coverage and correction guidance. An unavailable or non-five-player current-member set MUST return `current_roster_unavailable`. Invalid selectors, not-found teams, ambiguity, retry exhaustion, cancellation, and malformed upstream data MUST follow existing structured-error and safe-retry behavior.
- **FR-036**: The latest-lineup capability MUST have deterministic offline-capable coverage for ID/name resolution, newest-usable selection, five-record scan exhaustion, team-side verification, exact five-player validation, current-member equality, stand-in/roster-change mismatch, clean inference, every nullable ambiguity path, upstream partial failure/retry exhaustion, and MCP discovery/readability.
- **FR-037**: Professional-match eligibility MUST be a mandatory, non-configurable invariant for the player-fantasy capability. Every returned map MUST have affirmative professional-league provenance established from the hydrated match and authoritative league evidence; a professional player's participation alone is insufficient. Public matchmaking records and records with missing, zero, unknown, contradictory, or otherwise unverified league provenance MUST be excluded before patch/date/tier filtering and before `match_count` is applied. No input, including `tournament_tiers=[all]`, MAY disable or broaden this check, and the tool MUST expose no public/pub-match selector.

### Scope Boundaries

**In scope**:

- Read-only retrieval of a professional player's bounded recent-map fantasy evidence.
- Patch-version, UTC date, and upstream tournament-tier filtering aligned with the existing draft-analysis workflow.
- Compact match, opponent, hero, score, result, duration, and nullable series context.
- Raw and optionally calculated pre-modifier TI 2026 emblem scores.
- A versioned MCP reference for base scoring, quality tiers, traits, titles, evidence status, and series/stage aggregation.
- Focused retrieval of a professional team's five-player latest observed lineup and conservative match-derived position inference.

**Out of scope**:

- Managing a user's fantasy roster, inventory, rerolls, purchases, or Steam account.
- Automatically choosing the final lineup or promising an optimal/competitive result.
- Fabricating Madstone values, series groupings, trait/title effects, roles, or missing replay statistics.
- Claiming that a latest observed lineup is an authoritative current roster, or inferring positions from catalog labels, player-slot order, or final-match farm.
- Live/in-progress matches, public matchmaking under any input combination, amateur-only analysis by default, replay parse requests, or arbitrary raw-match exploration.
- Persisting user loadouts, hosting a multi-user service, OAuth, or any write operation.

### Key Entities

- **Professional Player**: A stable account ID and available professional display name used to resolve whose maps are analyzed.
- **Fantasy Match Evidence**: One eligible completed professional map containing match context, player/team/opponent/hero identities, nullable series identity, raw fantasy statistics, and sparse data-quality warnings.
- **Fantasy Statistic**: A typed count, duration, ratio, or attribution value with explicit zero-versus-null semantics and a TI 2026 emblem mapping.
- **Raw Emblem Score**: The per-map points produced from one fantasy statistic before quality, trait, or title modifiers.
- **Series**: A group identified only by a trustworthy series ID; a map may have no known series relationship.
- **Scoring Reference**: A versioned client-readable description of TI 2026 formulas, semantic definitions, modifiers, aggregation rules, provenance, and confidence.
- **Emblem Quality Tier**: One of five base multipliers applied to an emblem's raw points.
- **Trait**: A named fantasy modifier with scope, prerequisites, effect, stacking/order behavior, and evidence status.
- **Title**: A named fantasy modifier or eligibility rule with scope, effect, and evidence status.
- **Latest Observed Lineup**: Exactly five stable player IDs observed for one verified team in its newest usable parsed match, with source and coverage metadata.
- **Position Inference Evidence**: Nullable lane role, ten-minute last hits, inferred position, and inference status derived only from the selected parsed match.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across a fixture set of at least 30 professional maps covering at least three series, two patches, and three tournament tiers, 100% of returned maps satisfy all supplied filters, are newest first, and preserve correct player, hero, opponent, result, duration, score, and available series context.
- **SC-002**: For all 18 defined emblem metrics, 100% of complete fixture values and raw scores match the TI 2026 formulas; legitimate zeroes remain zero, unavailable values remain null, and every result reports Madstone unavailability exactly once.
- **SC-003**: In fixtures with absent series metadata, 100% of otherwise eligible maps remain available with a null series ID and 0% are assigned to an inferred series.
- **SC-004**: A client can resolve a known player and obtain up to 20 analysis-ready maps in one capability call when the account ID is known, or no more than two calls when name disambiguation is required.
- **SC-005**: The default 20-map response contains all required raw fantasy and match-context fields without arbitrary upstream records and can be analyzed without file export or command-line post-processing.
- **SC-006**: From the scoring reference alone, a client can correctly explain and calculate 100% of documented base formulas and quality-tier multipliers, identify the stage's two-best-maps/best-series rule, and distinguish every known trait/title effect from every unknown effect.
- **SC-007**: In usability validation, at least 90% of representative agent runs can compare two candidate player/emblem combinations using only the player capability and scoring reference, without a live rules search or clarification about field meaning.
- **SC-008**: 100% of tested invalid requests, ambiguous players, incomplete records, and exhausted upstream failures produce actionable bounded outcomes without inventing data or exposing secrets.
- **SC-009**: For fixture histories with a usable parsed lineup among the newest five completed matches whose IDs equal the five current-member IDs, 100% of responses select the newest usable match and return exactly those five account IDs with the correct source match ID.
- **SC-010**: For all clean 2-1-2 lineup fixtures, 100% of inferred positions match the specified lane/ten-minute-farm mapping; for every ambiguous fixture, 0 unsupported positions are emitted and affected values remain null.
- **SC-011**: An agent starting with a stable team ID can obtain five fantasy-ready player IDs in one lineup call and then request any player's fantasy evidence without name resolution or external post-processing.
- **SC-012**: 100% of fixtures containing a stand-in, recent roster change, incomplete current-member set, or selected/current membership mismatch return a cannot-infer outcome with zero inferred positions.
- **SC-013**: Across mixed-history fixtures containing otherwise valid public games, league-verified professional games, and games with missing or contradictory league provenance, 100% of returned maps are league-verified professional games and 0 public or unverified games are returned for every supported tier selection, including `all`.

## Assumptions

- "Last X" means the newest X completed professional maps remaining after all active filters; the default is 20 and maximum is 100.
- Filter behavior intentionally follows the existing draft-analysis capability: latest catalog patch and `premium` (Tier 1) by default, a patch-version expression when overridden, raw tier choices `premium`, `professional`, `amateur`, and mutually exclusive `all`, and inclusive UTC dates. These tiers narrow only maps that have already passed mandatory professional-league provenance verification; `all` means all eligible league tiers, never public matchmaking.
- Stable player account IDs are authoritative. Professional-name lookup exists for convenience and requires disambiguation when not unique.
- A team lineup is considered safe to return only when a newest-within-five usable parsed match and the team-player endpoint independently identify the same five account IDs; otherwise the agent receives a cannot-infer outcome.
- The supported professional-match source provides much, but not necessarily all, parsed replay evidence. Missing values are expected and remain analytically useful when clearly represented.
- Madstone collection is unavailable from the supported source at specification time. The field and warning preserve schema stability if a verified source becomes available later.
- Quality tiers, traits, and titles describe a user's fantasy configuration, not an intrinsic property of a historical match. Match association occurs only when a verified match-bound source or explicit future input establishes it.
- The supplied tier multipliers and emblem formulas are the baseline rules to preserve. Planning research will verify traits, titles, operation order, and source provenance; unverifiable rules remain explicitly unknown.
- Teamfight Participation is community-verified as ordinary whole-map kill participation rather than discrete physical fight attendance; the reference must retain Valve-documentation caveat language.
- Raw map scores do not by themselves select an optimal lineup. The client agent remains responsible for comparing candidates, consistency, trait synergy, reroll quality, and uncertainty.
- The existing local MCP server, response conventions, retry behavior, player/match data sources, and supported client compatibility remain the foundation for this additive feature.

## Dependencies

- Continued availability and documented behavior of the project's supported professional player, team-player membership, match, league-tier, patch-catalog, hero, team, and parsed replay data sources.
- Verifiable TI 2026 fantasy-rule sources for traits, titles, quality modifiers, and stage aggregation; missing documentation must be represented as uncertainty rather than filled by assumption.
- A network connection during live match retrieval; the scoring reference remains client-readable without a live rules search.
