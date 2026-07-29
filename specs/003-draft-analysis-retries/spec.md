# Feature Specification: Reliable Retries and Team Drafting Report

**Feature Branch**: `003-draft-analysis-retries`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "Investigate and harden OpenDota minute-rate-limit retries, then add a higher-level tool that produces a comparative drafting report for a professional team over a bounded recent-match lookback with patch, tournament-tier, side, result, first-ban, lane, economy, structure, objective, draft-order, matchup-knowledge, player, and parse-coverage evidence."

## Clarifications

### Session 2026-07-28

- Q: How is the default patch selected when no version expression is supplied? → A: Latest catalog patch by date
- Q: What jitter policy applies to fallback retry delays? → A: Additive 0–20% jitter
- Q: What are the default retry budgets? → A: 40s delay, 75s accumulated, 90s elapsed
- Q: What shape and guidance should the tournament-tier filter use? → A: Tier list; document and report all choices
- Q: How are detailed outcomes delivered for large lookbacks? → A: Paginate 10 default, 25 maximum

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Recover Safely From Rate Limits (Priority: P1)

An analysis agent can complete a read-only OpenDota operation through a temporary minute-rate-limit event without immediately repeating failed requests, while still receiving a clear bounded failure when the service cannot recover within the available retry budget.

**Why this priority**: The drafting report requires several upstream reads. If retry behavior amplifies throttling or gives up within a few seconds, every higher-level workflow remains unreliable.

**Independent Test**: Simulate rate-limit responses with missing, zero, malformed, short, valid, excessive, and date-form retry guidance; verify the selected waits, finite attempt count, cancellation behavior, recovery, and exhaustion outcome without real sleeping or network traffic.

**Acceptance Scenarios**:

1. **Given** a minute-rate-limit response without usable retry guidance, **When** later attempts continue to be rate limited, **Then** retry delays use base intervals of 2, 4, 8, 16, and 32 seconds, subject to bounded jitter, the configured budget, and caller deadline.
2. **Given** a positive standards-compliant retry delay, **When** it is no shorter than the safe fallback for that attempt and fits all budgets, **Then** no retry is sent before that delay has elapsed.
3. **Given** a zero, expired, malformed, non-finite, negative, or repeatedly too-short retry delay, **When** a retry is permitted, **Then** the response cannot cause an immediate retry and the safe fallback interval is used.
4. **Given** retry guidance longer than the remaining retry or caller budget, **When** the rate limit is encountered, **Then** the operation stops without sleeping past the budget and reports exhaustion plus the upstream-advised delay when safe to expose.
5. **Given** caller cancellation at any point, **When** the request or a retry wait is active, **Then** cancellation takes effect promptly and no further attempt is issued.

---

### User Story 2 - Generate a Focused Team Drafting Report (Priority: P2)

An analysis agent supplies a stable professional team ID and a recent-match lookback count, then receives a compact report of eligible games from the team's perspective. The report defaults to Tier 1 tournaments and the latest patch in OpenDota's patch catalog by release date, and can instead select other upstream tournament tiers or a family of catalog patch labels with a regular expression.

**Why this priority**: This is the primary user-facing capability: it turns match discovery and parsed match records into evidence that an analyst can use directly during opponent preparation.

**Independent Test**: Request a report for a known team across fixtures containing multiple patches, tournament tiers, and parse states; verify newest-first lookback selection, default latest-catalog-patch and Tier 1 behavior, regular-expression and tier overrides, stable team identity, bounded output, parse coverage, and no-result behavior.

**Acceptance Scenarios**:

1. **Given** the latest dated entry in OpenDota's patch catalog is `7.41`, **When** neither a version pattern nor tournament-tier filter is supplied, **Then** the newest 25 completed matches consume the lookback quota and only Tier 1 matches labeled exactly `7.41` are eligible for detailed analysis.
2. **Given** the version pattern `7[.]4[01]`, **When** the report is requested, **Then** completed matches labeled `7.40` or `7.41` within the lookback are eligible regardless of the latest catalog patch.
3. **Given** an explicit non-empty list of supported tournament tiers, **When** the report is requested, **Then** only matches in those tiers are eligible and the response shows the raw upstream tier for each match.
4. **Given** the 25-match lookback contains 20 parsed and 5 unparsed matches, **When** the report is returned, **Then** all 25 consume the quota, the response reports a 20/25 parse coverage rate, and each unparsed match is identified explicitly rather than disappearing from the report.
5. **Given** no other optional filters, **When** a report is requested, **Then** each returned game identifies the team and opponent, tournament and tier, patch, date, side, team-relative win/loss, first- or second-ban order when known, duration, parse status, analysis status, and data-completeness state.
6. **Given** an unknown team ID, invalid version expression, invalid or contradictory tier list, or lookback outside the documented bounds, **When** the tool is called, **Then** the request is rejected with correction guidance; a tier error enumerates `premium`, `professional`, `amateur`, and `all`, and team-name resolution is deferred to the existing lookup capability.
7. **Given** a valid request with no eligible games, **When** selection completes, **Then** the report returns an empty analyzed-game collection with the resolved team, applied filters, examined-match count, parsed/unparsed coverage, and exclusion counts rather than an error.

---

### User Story 3 - Compare Drafts Under Specific Conditions (Priority: P3)

An analysis agent can narrow the report by the team's side, match outcome, and whether the team made the first ban, allowing direct comparison of draft patterns under different competitive scenarios.

**Why this priority**: Draft tendencies are conditional. Team-relative filters prevent the agent from downloading a broad history and performing error-prone side and result transformations itself.

**Independent Test**: Exercise each filter alone and in combination across fixtures where the team is Radiant/Dire, wins/loses, and drafts first/second, including unknown draft order.

**Acceptance Scenarios**:

1. **Given** side `radiant`, result `loss`, and first ban `yes`, **When** the report is requested, **Then** every returned game satisfies all three conditions from the analyzed team's perspective.
2. **Given** no value for one or more filters, **When** the report is requested, **Then** the omitted dimensions do not exclude games.
3. **Given** degraded or missing pick/ban chronology, **When** a first-ban filter is active, **Then** the game is excluded as unknown and counted separately rather than guessed.
4. **Given** the selected team appears on neither or both match sides, **When** the record is evaluated, **Then** it is excluded with a data-quality reason.

---

### User Story 4 - Compare Draft and Game-State Evidence (Priority: P4)

An analysis agent can opt into cohesive detail groups to compare both teams' lanes, economy, structures, objectives, hero picks/bans, draft rounds, player assignments, matchup knowledge, and hero economy snapshots at the requested checkpoints.

**Why this priority**: Detailed evidence explains how draft choices translated into lanes and mid-game state, while opt-in groups keep the default response usable in a limited agent context.

**Independent Test**: Use one fully parsed match fixture with known players, draft actions, lane assignments, time series, structure events, Roshan events, and Tormentor events; request every field group separately and together, then verify team-relative symmetry and missing-data warnings.

**Acceptance Scenarios**:

1. **Given** complete per-player time series, **When** lane and economy detail is requested, **Then** both teams receive safelane, midlane, and offlane evidence at 10 minutes, team gold differences at 10 and 20 minutes, and per-hero net-worth snapshots at 10 and 20 minutes.
2. **Given** complete structure events, **When** structure detail is requested, **Then** both teams' cumulative losses at 10 and 20 minutes include lane-specific tier 1, tier 2, tier 3, melee-barracks, and ranged-barracks counts, plus non-lane tier 4 counts and totals.
3. **Given** attributable Roshan and Tormentor events, **When** objective detail is requested, **Then** both teams' counts and event times through 25 minutes are returned.
4. **Given** an authoritative draft and final lane assignments, **When** draft detail is requested, **Then** every pick and ban includes its action order and semantic phase/round where determinable, every pick includes its player, and every picked hero states which opposing lane heroes were already known at pick time.
5. **Given** missing or ambiguous parsed evidence, **When** any detail group is requested, **Then** the affected value is explicitly `unknown` or unavailable with a reason and is not replaced by a fabricated zero or inferred identity.
6. **Given** all detail groups are requested for the maximum lookback, **When** report pages are returned, **Then** each page contains at most the requested page size, no page exceeds 25 outcomes, an opaque cursor identifies the next page when one exists, and every group preserves the same newest-first game order and team perspective across pages.

### Edge Cases

- The patch catalog is unavailable, empty, or has no entry with a valid name and release date: default patch selection fails clearly and advises supplying a version pattern; it does not infer a patch from team matches.
- The latest catalog patch has no matching team games in the lookback: return an empty report with patch-exclusion counts; do not silently fall back to an older patch.
- A valid version expression matches no resolved patch labels: return an empty report with patch-exclusion counts.
- A version expression is malformed, longer than 64 characters, or cannot be evaluated within a safe bound: reject it without beginning match retrieval.
- The requested lookback reaches fewer completed matches than requested: examine all available matches and report the actual count and parse coverage denominator.
- A match in the lookback is unparsed: it still consumes one lookback slot and appears in coverage output with match identity, known tournament/patch/scenario metadata, parse status, analysis status, and the reason detailed evidence is unavailable.
- An unparsed match lacks metadata needed by an active patch, tournament-tier, or first-ban filter: retain it in lookback coverage, mark the filter disposition unknown, and do not silently include it among analyzed matches.
- A tournament has a missing or unrecognized upstream tier: retain the match in lookback coverage, report the raw value, and exclude it when a specific tier filter is active.
- A match ends before a 10-, 20-, or 25-minute checkpoint: return unavailable for that later checkpoint; do not reuse the final value as though it were a checkpoint observation.
- A time series lacks an exact checkpoint sample: use the latest observation at or before the checkpoint, disclose its timestamp, and mark unavailable if no prior observation exists.
- A player cannot be assigned uniquely to a lane or picked hero: preserve the hero and stable IDs, mark the association ambiguous, and do not use it for matchup-knowledge or lane classification.
- A team changes name or roster within the lookback: stable team IDs remain authoritative and each match retains match-time labels and players where available.
- Draft actions are missing, duplicated, or non-contiguous: preserve source order, mark chronology degraded, and leave semantic round and matchup knowledge unknown when they cannot be determined safely.
- A Captains Mode action sequence differs by patch or game mode: use the applicable documented sequence only when it can be identified; otherwise expose action order without claiming a semantic phase.
- An objective or structure event cannot be attributed to a team: report it as unattributed and mark the affected team comparison incomplete rather than assigning it by map side alone.
- Tormentor did not exist in the selected patch: report the objective as not applicable, distinct from zero taken and unknown data.
- Concurrent cache misses target the same upstream record: only the population owner performs retries; waiters do not multiply attempts.
- A cached failure is stale while upstream has recovered: normal failure-cache policy governs reuse, and the report identifies per-match upstream failures without presenting partial data as complete.
- A caller deadline, cancellation, or total retry budget prevents another attempt: stop promptly with a structured reason and no unbounded work.

## Requirements *(mandatory)*

### Functional Requirements

#### Retry Reliability

- **FR-001**: The system MUST retain finite, configurable limits for attempt count, individual delay, accumulated retry delay, and total elapsed operation time. Defaults MUST cap one delay at 40 seconds, accumulated retry delay at 75 seconds, and total elapsed time at 90 seconds. Total elapsed time MUST be measured monotonically from immediately before the initial upstream attempt through completion or exhaustion, including request time and retry waits.
- **FR-002**: The default retry policy MUST permit one initial attempt followed by up to five retries so the full 2, 4, 8, 16, and 32-second base sequence can be used when other budgets allow.
- **FR-003**: For retryable failures without usable upstream guidance, the base delay before successive retries MUST be 2, 4, 8, 16, and 32 seconds. Each delay MUST add independently sampled jitter from 0% through 20% of that attempt's base delay, making the base delay the minimum and 120% of base the maximum, without exceeding configured delay or elapsed-time budgets.
- **FR-004**: A `Retry-After` value MUST be considered syntactically usable only when it is a positive finite delay in the standard seconds form or an HTTP date strictly in the future.
- **FR-005**: For a usable `Retry-After`, the actual wait MUST be at least both the upstream-advised delay and the safe fallback base for that attempt. This prevents a repeatedly short header from causing a tight retry loop while still honoring a longer upstream instruction.
- **FR-006**: Zero, negative, expired, malformed, and non-finite retry guidance MUST be treated as unusable and MUST fall back to FR-003.
- **FR-007**: If the required wait cannot fit within the remaining retry budget or caller deadline, the system MUST stop before sleeping and return a structured exhausted error that distinguishes attempt exhaustion, delay-budget exhaustion, deadline exhaustion, and caller cancellation where applicable.
- **FR-008**: A minute-rate-limit response, an unknown rate-limit response, eligible timeouts, connection failures, and retryable server failures MUST use the bounded retry policy only for operations safe to repeat.
- **FR-010**: Retry diagnostics MUST record the failure class, attempt number, selected delay source, selected delay, and exhaustion reason without recording API keys or full upstream response bodies.
- **FR-011**: Caller cancellation MUST interrupt an active request or retry wait and MUST prevent subsequent attempts.
- **FR-012**: Cache hits MUST perform no upstream retry, and concurrent callers waiting for the same cache population MUST NOT create independent retry sequences for that same population attempt.
- **FR-013**: Automated coverage MUST verify recovery and exhaustion for all in-scope retryable status classes, all `Retry-After` validity classes, repeated short guidance, budgets, cancellation, cache coordination, and non-retryable failures without real delays.

#### Team Drafting Report Inputs and Selection

- **FR-014**: The server MUST expose one higher-level team drafting report capability that accepts a positive professional team ID and MUST NOT accept a team name in place of that ID; callers use the existing team lookup capability for ID resolution.
- **FR-015**: The capability MUST accept `lookback_count` from 1 through 100, defaulting to 25, meaning the number of the team's newest completed professional matches examined before parse status, tournament tier, patch, and scenario filters are applied.
- **FR-016**: Without a version expression, the capability MUST retrieve OpenDota's patch catalog, select the valid entry with the greatest release date, and apply that entry's exact human-readable patch label to the lookback. Catalog order and patch identifiers MUST NOT be treated as recency guarantees. If no valid dated entry exists, the request MUST fail with correction guidance rather than infer a patch from team matches.
- **FR-017**: The capability MUST accept an optional regular expression of at most 64 characters, applied as a full-string match to human-readable patch labels; when present, it MUST replace the default exact-latest-patch filter.
- **FR-018**: The capability MUST reject malformed or unsafe-to-evaluate version expressions before retrieving match details and MUST explain the full-string matching behavior in its public description.
- **FR-019**: The capability MUST support independently combinable, team-relative filters for side (`radiant` or `dire`), result (`win` or `loss`), and first ban (`yes` or `no`), with omission meaning either value is allowed.
- **FR-019a**: The capability MUST accept a non-empty tournament-tier list containing one or more distinct upstream league-tier values from `premium`, `professional`, and `amateur`, or the single value `all`. The default MUST be `[premium]`, presented to users as Tier 1. `all` MUST NOT be combined with another value, and the tool MUST NOT infer numeric labels for other upstream tiers. The public tool description and every invalid-tier error MUST enumerate all four accepted values and explain that named tiers may be combined while `all` is mutually exclusive.
- **FR-020**: First-ban order MUST be determined from the earliest authoritative ban action in the match: the acting team is `first` and the other team is `second`. If this cannot be determined, the value MUST be `unknown` and MUST not satisfy a `yes` or `no` filter.
- **FR-021**: Matches MUST be returned newest first and every response page MUST report the resolved team, requested and examined lookback counts, active tournament-tier, patch, and scenario filters, analyzed count, and exclusion or unknown-disposition counts by reason.
- **FR-021a**: Every completed match, parsed or unparsed, MUST consume one slot in the lookback before filters are applied. The system MUST NOT scan farther back to replace an unparsed or filtered-out match merely to reach a target analyzed-match count.
- **FR-021b**: The response MUST include parse coverage for the complete lookback and after each filter stage, including parsed count, unparsed count, denominator, percentage, and the IDs and known metadata of unparsed matches, so analysts can assess selection bias.
- **FR-021c**: Each unparsed match in the lookback MUST appear as an explicit coverage or game outcome with `parse_status=unparsed`, `analysis_status=unavailable`, known core metadata, filter disposition, and unavailable-detail reasons; optional evidence MUST not be fabricated.
- **FR-021d**: Match and coverage outcomes MUST be paginated after selection in stable newest-first order. The request MUST accept a page size from 1 through 25, defaulting to 10, and an opaque continuation cursor. Each page MUST repeat the report-level filter, selection-count, and complete-lookback parse-coverage context; MUST expose the returned-outcome count and next cursor when more outcomes remain; and MUST reject invalid, expired, or request-mismatched cursors with correction guidance. Pagination MUST NOT repeat or skip outcomes when the underlying report snapshot is unchanged.
- **FR-022**: An invalid team ID, unknown team, invalid input, unavailable default patch, or request-wide upstream failure MUST produce a structured tool error; invalid-tier errors MUST enumerate `premium`, `professional`, `amateur`, and `all` as correction choices. Per-match missing or malformed data MUST produce a sparse per-match outcome so other matches remain usable.

#### Response Shape and Comparative Evidence

- **FR-023**: The default response for each game or coverage outcome MUST contain match ID, UTC start time, tournament identity and raw upstream tier, patch ID and label, analyzed team and opponent identities, analyzed-team side and result, first- or second-ban order when known, duration, parse status, analysis status, filter disposition, and completeness warnings.
- **FR-024**: Rich evidence MUST be available through additive field groups named `draft`, `lanes`, `economy`, `structures`, and `objectives`; unsupported group names MUST be rejected with the valid choices, and selecting all groups MUST produce the complete requested report.
- **FR-025**: Every comparative group MUST represent both the analyzed team and its opponent using the same fields and checkpoint definitions, while clearly retaining the analyzed-team perspective.
- **FR-026**: The `draft` group MUST return every pick and ban in best-known chronological order with pick/ban type, acting team, hero ID/name, source action order, semantic pick/ban phase and round where determinable, and chronology quality.
- **FR-027**: Every pick in the `draft` group MUST identify the player by professional name and stable account ID when available, using the existing identity fallback rules and never guessing an ambiguous player.
- **FR-028**: For each picked hero, the `draft` group MUST report whether its lane matchup was known when it was picked, the opposing heroes already known, and the evidence quality. A mid hero is matchup-known when the opposing final mid hero was picked earlier; a non-mid hero is matchup-known only when both opposing final laners were picked earlier.
- **FR-029**: Matchup-knowledge assessment MUST use final parsed lane assignments joined to authoritative draft order. It MUST be `unknown` when final lane assignment, hero-player mapping, opposing lane composition, or draft chronology is incomplete or ambiguous.
- **FR-030**: The `lanes` group MUST report safelane, midlane, and offlane participants for both teams and, at 10 minutes, combined lane net-worth difference, experience difference, and last-hit difference from each team's perspective.
- **FR-031**: Each lane MUST receive a transparent heuristic assessment: `advantaged` when it leads in both net worth and experience, `disadvantaged` when it trails in both, `even` when both are equal, `mixed` when the signals disagree, and `unknown` when either primary signal is unavailable. Last hits are supporting evidence and do not override the classification.
- **FR-032**: The `economy` group MUST report team gold difference at 10 and 20 minutes from both Radiant/Dire and analyzed-team perspectives, plus every hero's team, player identity, hero identity, lane, observed net worth at 10 and 20 minutes, and actual sample timestamp.
- **FR-033**: A per-player economy value MUST be labeled net worth only when the documented parsed-match time series supports that meaning; current gold, final net worth, or another proxy MUST NOT be silently substituted. An unsupported checkpoint MUST be unavailable with a reason.
- **FR-034**: The `structures` group MUST report cumulative structures lost by each team at 10 and 20 minutes, broken down into top/mid/bottom tier 1, tier 2, and tier 3 towers; top/mid/bottom melee and ranged barracks; non-lane tier 4 towers; and category and overall totals.
- **FR-035**: Structure checkpoint counts MUST come from attributable timestamped destruction evidence. Final structure-status values MAY validate completeness but MUST NOT be used to invent destruction timing.
- **FR-036**: The `objectives` group MUST report, for each team, Roshan and Tormentor counts through 25 minutes, each attributable event time, and first-take time; it MUST distinguish zero taken, unattributed event, unavailable parsed evidence, and not applicable for the patch.
- **FR-037**: All 10-, 20-, and 25-minute fields MUST use game-clock time, use the latest observation at or before a checkpoint when exact samples are absent, disclose the observation time, and return unavailable if the match ended or no observation exists before that checkpoint.
- **FR-038**: Each game and each optional group MUST expose completeness and data-quality warnings sufficient to distinguish complete, partial, unknown, and not-applicable evidence; missing values MUST never be represented as zero unless zero is established by complete evidence.
- **FR-039**: The tool description MUST document the slim default, field groups, 25-match lookback default and 100-match maximum, outcome pagination with its 10-item default, 25-item maximum, and opaque continuation cursor, unparsed-match quota and coverage behavior, Tier 1 (`premium`) default, all tournament-tier choices (`premium`, `professional`, `amateur`, and mutually exclusive `all`) and named-tier combination behavior, patch-expression semantics, team-relative filters, checkpoint rules, heuristic lane definition, possible partial data, and meaningful upstream exhaustion outcomes.
- **FR-040**: Authentication remains optional and reuses existing OpenDota configuration; no new identity, authorization, or secret-returning behavior is introduced.

### Key Entities *(include if feature involves data)*

- **Retry Policy**: Finite limits and decision rules for attempts, fallback bases, jitter, upstream guidance, delay budget, elapsed budget, caller deadline, cancellation, and exhaustion reason.
- **Rate-Limit Observation**: One in-scope throttling response classified as minute or unknown, with sanitized guidance and remaining-minute metadata when available.
- **Drafting Report Request**: Team ID, bounded lookback, optional version expression, tournament-tier and scenario filters, and selected evidence groups.
- **Drafting Report**: Resolved team context, filter summary, selection counts, complete-lookback parse-coverage measurements, a stable paginated sequence of per-match outcomes, continuation metadata, and report-level warnings.
- **Parse Coverage**: Counts and identities of parsed and unparsed matches in the quota window and after each filter stage, including denominators, rates, dispositions, and known metadata.
- **Match Comparison**: One eligible game represented symmetrically for the analyzed team and opponent, with core context and selected evidence groups.
- **Draft Action**: Ordered pick or ban with acting team, hero, semantic phase/round, player for picks, chronology quality, and matchup-knowledge evidence.
- **Lane Assessment**: Final lane participants plus 10-minute net-worth, experience, and last-hit comparisons and the declared heuristic outcome.
- **Checkpoint Snapshot**: A requested game-clock checkpoint, actual observation time, value, perspective, and availability quality.
- **Structure Ledger**: Timestamped and attributable tower/barracks losses summarized by team, lane, tier/type, checkpoint, and total.
- **Objective Ledger**: Timestamped and attributable Roshan/Tormentor events summarized through 25 minutes with zero/unknown/not-applicable distinctions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In deterministic rate-limit tests, 100% of missing, zero, expired, malformed, and repeatedly too-short retry guidance avoids an immediate retry and waits within the inclusive ranges 2–2.4, 4–4.8, 8–9.6, 16–19.2, and 32–38.4 seconds while budget remains.
- **SC-002**: In deterministic recovery tests, the default 40-second individual-delay and 75-second accumulated-delay caps permit the complete maximum-jitter fallback sequence, 100% of operations that receive a success within all active budgets return that success, and 100% that exceed an attempt, delay, 90-second elapsed-time, caller-deadline, or cancellation boundary stop without one extra request.
- **SC-003**: A single uncached report at the maximum lookback never examines more than 100 team matches and does not create duplicate upstream retry sequences for shared cache-population work.
- **SC-004**: For a fixture set spanning three patch labels and tournament tiers, 100% of default analyzed matches are `premium` Tier 1 matches on the latest valid patch-catalog entry by release date, and 100% of version-pattern and tier-filter reports contain only matches satisfying both supplied filters.
- **SC-005**: Across side, result, and first-ban acceptance fixtures, 100% of returned games satisfy every active filter from the analyzed team's perspective, with unknown values excluded and counted rather than guessed.
- **SC-006**: For complete parsed-match fixtures, 100% of requested core and optional fields agree with source draft order, player assignments, lane time series, structure events, objective events, and team perspective at the defined checkpoints.
- **SC-007**: For incomplete fixtures, 100% of unavailable evidence is labeled unknown, partial, or not applicable; no missing checkpoint, structure, objective, player, lane, or matchup value is reported as an established zero or fact.
- **SC-007a**: For every fixture set, parsed count plus unparsed count equals the examined lookback count, all unparsed match IDs are present in coverage output, and the reported parse percentage equals parsed count divided by the examined count.
- **SC-008**: An analysis agent can obtain the first page of a default team report in one tool call after resolving a team ID, can request all documented groups without external JSON post-processing, and can retrieve every remaining outcome by following only the returned opaque continuation cursors.
- **SC-009**: Every response contains at most 25 match or coverage outcomes from a maximum 100-match quota window, and every page contains core report and complete-lookback parse-coverage context so users can assess bias before requesting or continuing detailed evidence.

## Assumptions

- The feature extends the existing professional team lookup, team-match discovery, draft retrieval, shared response cache, and structured error behavior rather than replacing them.
- `lookback_count` is the recent completed-match quota window examined before parse status and all filters, not a guarantee that the report will return that many analyzed games. Unparsed matches consume quota exactly like parsed matches.
- For tournament-tier filtering, Tier 1 means OpenDota's `premium` league tier. Other filter values retain OpenDota's raw `professional` and `amateur` labels because no unsupported Tier 2/Tier 3 mapping is inferred.
- OpenDota's patch catalog is authoritative for default patch selection. The valid entry with the greatest release date supplies the exact default label independently of the selected team's match history and active tournament-tier or scenario filters.
- Patch expressions are full-string regular-expression matches against labels supplied by OpenDota's patch catalog; a caller wanting patches `7.40` and `7.41` can use `7[.]4[01]`.
- Parsed OpenDota records are expected to provide draft actions, player lane assignments, per-minute gold/experience/last-hit series, Radiant gold advantage, and timestamped objectives when parsing is complete. Planning must verify the exact upstream meaning and availability of every consumed field before implementation.
- Net-worth terminology is contingent on verified upstream semantics. If the available per-minute value is only an approximation or a differently defined gold measure, the public report must name it accurately and mark exact net worth unavailable.
- Lane outcome is intentionally a transparent descriptive heuristic, not a claim that net worth and experience fully determine strategic lane success.
- Semantic draft phases vary with game mode and patch; action order remains useful even when a trustworthy phase mapping is unavailable.
- Current official OpenDota source configures 60 unauthenticated calls per minute and 300 calls per minute with an API key using a fixed minute bucket. Its current rate-limit response path exposes remaining-minute metadata and a 429 body but does not set `Retry-After`; therefore missing guidance is an expected condition, while proxy-provided guidance may still be honored under the safety rules above.
- Current local defaults (3 attempts, 0.25-second fallback base, 5-second cap, and 10-second delay budget) are insufficient for the requested minute-window recovery behavior and are in scope for revision.
- Daily quota exhaustion behavior is outside the scope of this feature and remains unchanged.
- All upstream operations used by this report are read-only and safe to repeat; caller deadlines and cancellation remain authoritative.
- No new data persistence, user authentication, alternate upstream provider, predictive draft recommendation, or aggregate cross-match trend scoring is included in this feature.
