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
4. **Given** the 25-match lookback contains 20 parsed and 5 unparsed matches, **When** the report is returned, **Then** all 25 consume the quota and the response reports parsed and unparsed counts without expanding every unparsed match into a diagnostic record.
5. **Given** no other optional filters, **When** a report is requested, **Then** each returned eligible game identifies the match, tournament, patch label, date, analyzed team, opponent, side, team-relative win/loss, first- or second-ban order when known, and duration.
6. **Given** an unknown team ID, invalid version expression, invalid or contradictory tier list, or lookback outside the documented bounds, **When** the tool is called, **Then** the request is rejected with correction guidance; a tier error enumerates `premium`, `professional`, `amateur`, and `all`, and team-name resolution is deferred to the existing lookup capability.
7. **Given** a valid request with no eligible games, **When** selection completes, **Then** the report returns an empty match collection with the resolved team, applied filters, examined-match count, and parsed/unparsed coverage rather than an error.

---

### User Story 3 - Compare Drafts Under Specific Conditions (Priority: P3)

An analysis agent can narrow the report by the team's side, match outcome, and whether the team made the first ban, allowing direct comparison of draft patterns under different competitive scenarios.

**Why this priority**: Draft tendencies are conditional. Team-relative filters prevent the agent from downloading a broad history and performing error-prone side and result transformations itself.

**Independent Test**: Exercise each filter alone and in combination across fixtures where the team is Radiant/Dire, wins/loses, and drafts first/second, including unknown draft order.

**Acceptance Scenarios**:

1. **Given** side `radiant`, result `loss`, and first ban `yes`, **When** the report is requested, **Then** every returned game satisfies all three conditions from the analyzed team's perspective.
2. **Given** no value for one or more filters, **When** the report is requested, **Then** the omitted dimensions do not exclude games.
3. **Given** degraded or missing pick/ban chronology, **When** a first-ban filter is active, **Then** the game is excluded rather than guessed.
4. **Given** the selected team appears on neither or both match sides, **When** the record is evaluated, **Then** it is excluded without exposing internal evaluation diagnostics.

---

### User Story 4 - Compare Draft and Game-State Evidence (Priority: P4)

An analysis agent can opt into cohesive detail groups to compare both teams' lanes, economy, structures, objectives, hero picks/bans, player assignments, matchup knowledge, and hero economy snapshots at the requested checkpoints.

**Why this priority**: Detailed evidence explains how draft choices translated into lanes and mid-game state, while opt-in groups keep the default response usable in a limited agent context.

**Independent Test**: Use one fully parsed match fixture with known players, draft actions, lane assignments, time series, structure events, Roshan events, and Tormentor events; request every field group separately and together, then verify team-relative symmetry and sparse handling of missing data.

**Acceptance Scenarios**:

1. **Given** complete parsed time series, **When** lane and economy detail is requested, **Then** the report returns safelane, midlane, and offlane participants with experience and last-hit differences at 10 minutes, analyzed-team gold differences at 10 and 20 minutes, and each hero's OpenDota total-gold value at 10 and 20 minutes.
2. **Given** complete structure events, **When** structure detail is requested, **Then** both teams' cumulative loss-key lists at 10 and 20 minutes identify lane-specific tier 1, tier 2, tier 3, melee-barracks, ranged-barracks, and non-lane tier 4 structures without zero-filled counter trees.
3. **Given** attributable Roshan and Tormentor events, **When** objective detail is requested, **Then** both teams' event-time lists through 25 minutes are returned and allow counts and first-take times to be derived.
4. **Given** an authoritative draft and final lane assignments, **When** draft detail is requested, **Then** every pick and ban includes its action order and per-team pick/ban round, every uniquely mapped pick includes its player, and every picked hero states which opposing lane heroes were already known at pick time.
5. **Given** missing or ambiguous parsed evidence, **When** any detail group is requested, **Then** the affected nullable field is `null` or omitted and is not replaced by a fabricated zero or inferred identity.
6. **Given** all detail groups are requested for the maximum lookback, **When** report pages are returned, **Then** each page contains at most the requested page size, no page exceeds 25 outcomes, an opaque cursor identifies the next page when one exists, and every group preserves the same newest-first game order and team perspective across pages.

### Edge Cases

- The patch catalog is unavailable, empty, or has no entry with a valid name and release date: default patch selection fails clearly and advises supplying a version pattern; it does not infer a patch from team matches.
- The latest catalog patch has no matching team games in the lookback: return an empty report; do not silently fall back to an older patch.
- A valid version expression matches no resolved patch labels: return an empty report.
- A version expression is malformed, longer than 64 characters, or cannot be evaluated within a safe bound: reject it without beginning match retrieval.
- The requested lookback reaches fewer completed matches than requested: examine all available matches and report the actual count and parse coverage denominator.
- A match in the lookback is unparsed: it still consumes one lookback slot and contributes to the unparsed coverage count, but is not expanded into a match result or diagnostic explanation.
- An unparsed match lacks metadata needed by an active patch, tournament-tier, or first-ban filter: retain it only in the lookback coverage count and do not silently include it among eligible matches.
- A tournament has a missing or unrecognized upstream tier: exclude it when a specific tier filter is active without exposing internal source or evaluation details.
- A match ends before a 10-, 20-, or 25-minute checkpoint: return `null` for that later checkpoint; do not reuse the final value as though it were a checkpoint observation.
- A time series lacks an exact checkpoint sample: use the latest observation at or before the checkpoint and return `null` if no prior observation exists.
- A player cannot be assigned uniquely to a lane or picked hero: preserve the hero name, omit the ambiguous player, and do not use the association for matchup knowledge.
- A team changes name or roster within the lookback: stable team IDs remain authoritative and each match retains match-time labels and players where available.
- Draft actions are missing, duplicated, or cannot be ordered unambiguously: preserve best-known order but omit round and matchup knowledge when they cannot be determined safely.
- An objective or structure event cannot be attributed to a team: omit it from team totals rather than assigning it by map side alone or exposing a diagnostic event list.
- Tormentor did not exist in the selected patch: return `null`, distinct from a verified empty event-time list.
- Concurrent cache misses target the same upstream record: only the population owner performs retries; waiters do not multiply attempts.
- A cached failure is stale while upstream has recovered: normal failure-cache policy governs reuse; a failed match detail contributes to coverage but does not add a verbose per-match error object.
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
- **FR-021**: Eligible matches MUST be returned newest first and every response page MUST report the resolved team, active filters, and only the examined, parsed, and unparsed lookback counts.
- **FR-021a**: Every completed match, parsed or unparsed, MUST consume one slot in the lookback before filters are applied. The system MUST NOT scan farther back to replace an unparsed or filtered-out match merely to reach a target analyzed-match count.
- **FR-021b**: Parse coverage MUST be limited to aggregate parsed and unparsed counts for the complete lookback. The public response MUST NOT include per-filter-stage coverage, filter evaluations, or explanations of why individual matches are unparsed or excluded.
- **FR-021c**: Unparsed, filtered-out, malformed, and failed-detail matches MUST NOT be expanded into public match outcomes. They contribute only to the compact lookback summary; optional evidence MUST never be fabricated.
- **FR-021d**: Eligible matches MUST be paginated after selection in stable newest-first order. The request MUST accept a page size from 1 through 25, defaulting to 10, and an opaque continuation cursor. Each page MUST repeat the resolved team, active filters, and compact lookback summary; MUST expose a next cursor only when more matches remain; and MUST reject invalid, expired, or request-mismatched cursors with correction guidance. Pagination MUST NOT repeat or skip matches when the report snapshot is unchanged.
- **FR-022**: An invalid team ID, unknown team, invalid input, unavailable default patch, or request-wide upstream failure MUST produce a concise structured tool error; invalid-tier errors MUST enumerate `premium`, `professional`, `amateur`, and `all` as correction choices. A per-match failure MUST NOT fail otherwise usable matches or expose internal diagnostics.

#### Response Shape and Comparative Evidence

- **FR-023**: The default response for each eligible match MUST contain only match ID, UTC start time, duration, tournament name and tier, patch label, analyzed-team name, opponent name, analyzed-team side and result, and ban order when known. Team tags, league IDs, patch IDs, parse/analysis statuses, filter evaluations/dispositions, source/provenance fields, completeness objects, and diagnostic warnings MUST NOT be included.
- **FR-024**: Rich evidence MUST be available through additive field groups named `draft`, `lanes`, `economy`, `structures`, and `objectives`; unsupported group names MUST be rejected with the valid choices, and selecting all groups MUST produce the complete requested report.
- **FR-025**: Comparative groups MUST use the analyzed-team perspective and compact paired fields or differences rather than duplicating equivalent positive and negative views for both teams.
- **FR-026**: The `draft` group MUST return every pick and ban in best-known chronological order with one action order, pick/ban type, per-team round, acting-team name, and hero name. `type` is the phase. For each team independently, actions MUST be traversed by global order; consecutive actions of one type form one round for that type, and the next run of that type after the other type increments its round. Thus each team has its own ban rounds 1..N and pick rounds 1..N. Round MUST be omitted when action order is ambiguous. Hero IDs, source indexes, duplicate order fields, chronology-quality fields, and source metadata MUST NOT be returned.
- **FR-027**: Every pick in the `draft` group SHOULD identify the player by professional name when uniquely available, using existing identity fallback rules and never guessing an ambiguous player. Player account IDs are omitted from this report.
- **FR-028**: For each picked hero, the `draft` group MUST report whether its lane matchup was known when it was picked and the opposing hero names already known. A mid hero is matchup-known when the opposing final mid hero was picked earlier; a non-mid hero is matchup-known only when both opposing final laners were picked earlier.
- **FR-029**: Matchup-knowledge assessment MUST use final parsed lane assignments joined to authoritative draft order. It MUST be omitted when final lane assignment, hero-player mapping, opposing lane composition, or draft chronology is incomplete or ambiguous.
- **FR-030**: The `lanes` group MUST report safelane, midlane, and offlane hero-name lists for the analyzed team and opponent, plus analyzed-team experience and last-hit differences at 10 minutes.
- **FR-031**: Missing lane participants or checkpoint differences MUST be represented sparsely as omitted or `null`; the response MUST NOT add availability, evidence-quality, or reason wrappers.
- **FR-032**: The `economy` group MUST report analyzed-team gold difference and each hero's OpenDota total-gold value at 10 and 20 minutes, using hero names and optional player names. These values MUST come from `radiant_gold_adv` and `gold_t` and MUST be labeled gold rather than exact net worth.
- **FR-034**: The `structures` group MUST report compact lists of structure keys lost by the analyzed team and opponent through 10 and 20 minutes. Keys distinguish top/mid/bottom tier 1-3 towers, melee/ranged barracks, and tier 4 towers without emitting every zero-valued counter or redundant totals.
- **FR-035**: Structure checkpoint counts MUST come from attributable timestamped destruction evidence. Final structure-status values MAY validate completeness but MUST NOT be used to invent destruction timing.
- **FR-036**: The `objectives` group MUST report Roshan and Tormentor attributable event-time lists through 25 minutes for the analyzed team and opponent. A verified empty list means zero; `null` means unavailable or not applicable. Counts and first-take times MUST NOT duplicate information derivable from the event-time list.
- **FR-037**: All 10-, 20-, and 25-minute fields MUST use game-clock time and the latest observation at or before a checkpoint when exact samples are absent. The public response MUST NOT expose observation timestamps or sampling diagnostics.
- **FR-038**: Missing optional evidence MUST be represented by omission or `null`, while verified counts may be zero and verified event collections may be empty. The public response MUST NOT expose broad completeness, availability, evidence-quality, source, or warning objects.
- **FR-039**: The tool description MUST document the slim default, field groups, 25-match lookback default and 100-match maximum, match pagination with its 10-item default, 25-item maximum, and opaque continuation cursor, aggregate parse coverage behavior, Tier 1 (`premium`) default, all tournament-tier choices (`premium`, `professional`, `amateur`, and mutually exclusive `all`) and named-tier combination behavior, patch-expression semantics, team-relative filters, checkpoint rules, possible sparse data, and bounded upstream exhaustion.
- **FR-040**: Authentication remains optional and reuses existing OpenDota configuration; no new identity, authorization, or secret-returning behavior is introduced.

### Key Entities *(include if feature involves data)*

- **Retry Policy**: Finite limits and decision rules for attempts, fallback bases, jitter, upstream guidance, delay budget, elapsed budget, caller deadline, cancellation, and exhaustion reason.
- **Rate-Limit Observation**: One in-scope throttling response classified as minute or unknown, with sanitized guidance and remaining-minute metadata when available.
- **Drafting Report Request**: Team ID, bounded lookback, optional version expression, tournament-tier and scenario filters, and selected evidence groups.
- **Drafting Report**: Resolved team, active filters, compact lookback coverage, eligible matches, and continuation cursor.
- **Parse Coverage**: Aggregate examined, parsed, and unparsed counts for the quota window.
- **Match Comparison**: One eligible game from the analyzed team's perspective, with a minimal core and selected evidence groups.
- **Draft Action**: Ordered pick or ban with its per-team type round, acting-team name, hero name, optional player name, and compact matchup knowledge.
- **Lane Comparison**: Final analyzed-team and opponent hero-name lists plus 10-minute experience and last-hit differences.
- **Structure Ledger**: Compact structure keys lost by each team through 10 and 20 minutes.
- **Objective Ledger**: Attributable Roshan/Tormentor event-time lists through 25 minutes, or `null` when unsupported.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In deterministic rate-limit tests, 100% of missing, zero, expired, malformed, and repeatedly too-short retry guidance avoids an immediate retry and waits within the inclusive ranges 2–2.4, 4–4.8, 8–9.6, 16–19.2, and 32–38.4 seconds while budget remains.
- **SC-002**: In deterministic recovery tests, the default 40-second individual-delay and 75-second accumulated-delay caps permit the complete maximum-jitter fallback sequence, 100% of operations that receive a success within all active budgets return that success, and 100% that exceed an attempt, delay, 90-second elapsed-time, caller-deadline, or cancellation boundary stop without one extra request.
- **SC-003**: A single uncached report at the maximum lookback never examines more than 100 team matches and does not create duplicate upstream retry sequences for shared cache-population work.
- **SC-004**: For a fixture set spanning three patch labels and tournament tiers, 100% of default analyzed matches are `premium` Tier 1 matches on the latest valid patch-catalog entry by release date, and 100% of version-pattern and tier-filter reports contain only matches satisfying both supplied filters.
- **SC-005**: Across side, result, and first-ban acceptance fixtures, 100% of returned games satisfy every active filter from the analyzed team's perspective, with unknown values excluded rather than guessed.
- **SC-006**: For complete parsed-match fixtures, 100% of requested core and optional fields agree with source draft order, player assignments, lane time series, structure events, objective events, and analyzed-team perspective at the defined checkpoints; no response contains a team tag, league ID, patch ID, hero ID, account ID, source/provenance field, or filter evaluation.
- **SC-007**: For incomplete fixtures, 100% of missing evidence is omitted or `null`; no missing checkpoint, structure, objective, player, lane, or matchup value is reported as an established zero or fact, and no diagnostic reason wrapper is added.
- **SC-007a**: For every fixture set, parsed count plus unparsed count equals the examined lookback count, with no per-filter-stage coverage breakdown.
- **SC-008**: An analysis agent can obtain the first page of a default team report in one tool call after resolving a team ID, can request all documented groups without external JSON post-processing, and can retrieve every remaining outcome by following only the returned opaque continuation cursors.
- **SC-009**: Every response contains at most 25 eligible matches from a maximum 100-match quota window, and every page contains the compact lookback coverage needed to assess parse bias.

## Assumptions

- The feature extends the existing professional team lookup, team-match discovery, draft retrieval, shared response cache, and structured error behavior rather than replacing them.
- `lookback_count` is the recent completed-match quota window examined before parse status and all filters, not a guarantee that the report will return that many analyzed games. Unparsed matches consume quota exactly like parsed matches.
- For tournament-tier filtering, Tier 1 means OpenDota's `premium` league tier. Other filter values retain OpenDota's raw `professional` and `amateur` labels because no unsupported Tier 2/Tier 3 mapping is inferred.
- OpenDota's patch catalog is authoritative for default patch selection. The valid entry with the greatest release date supplies the exact default label independently of the selected team's match history and active tournament-tier or scenario filters.
- Patch expressions are full-string regular-expression matches against labels supplied by OpenDota's patch catalog; a caller wanting patches `7.40` and `7.41` can use `7[.]4[01]`.
- Parsed OpenDota records are expected to provide draft actions, player lane assignments, per-minute total-gold/experience/last-hit series, Radiant gold advantage, and timestamped objectives when parsing is complete. Planning must verify the exact upstream meaning and availability of every consumed field before implementation.
- Current official OpenDota source configures 60 unauthenticated calls per minute and 300 calls per minute with an API key using a fixed minute bucket. Its current rate-limit response path exposes remaining-minute metadata and a 429 body but does not set `Retry-After`; therefore missing guidance is an expected condition, while proxy-provided guidance may still be honored under the safety rules above.
- Current local defaults (3 attempts, 0.25-second fallback base, 5-second cap, and 10-second delay budget) are insufficient for the requested minute-window recovery behavior and are in scope for revision.
- Daily quota exhaustion behavior is outside the scope of this feature and remains unchanged.
- All upstream operations used by this report are read-only and safe to repeat; caller deadlines and cancellation remain authoritative.
- No new data persistence, user authentication, alternate upstream provider, predictive draft recommendation, or aggregate cross-match trend scoring is included in this feature.
