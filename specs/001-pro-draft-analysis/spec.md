# Feature Specification: Professional Draft Analysis MCP

**Feature Branch**: `main`

**Created**: 2026-07-15

**Status**: Draft

**Input**: User description: "Create a locally runnable MCP server, including initial project scaffolding, that uses OpenDota data to retrieve ordered hero picks and bans for specified professional match IDs, all available matches from a professional tournament through bounded pages, and recent matches for a professional team found by ID or name with date, side, and result filters."

## Clarifications

### Session 2026-07-15

- Q: How should pagination behave when an ongoing tournament gains new matches between page requests? → A: Snapshot traversal; continuation pages retain the first page's dataset boundary, and new matches appear after restarting from page one.
- Q: How should tournament and professional-team name searches match queries? → A: Prefer normalized exact name or tag matches, then return ranked substring matches for disambiguation.
- Q: How should the draft tool handle missing, duplicate, or non-contiguous action-order values? → A: Return all actions in upstream array sequence and mark the draft order as degraded.
- Q: Should team-match pagination also retain the first page's dataset boundary? → A: Yes; team and tournament pagination both use snapshot traversal.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Inspect Match Drafts (Priority: P1)

An analysis agent submits one or more professional match IDs and receives a compact, chronological account of each hero pick and ban, with enough match, team, patch, and player identity context to compare drafting decisions across games.

**Why this priority**: The ordered draft is the primary evidence required for hero ban/pick analysis; match discovery is only useful if the selected matches can be inspected accurately.

**Independent Test**: Submit known professional match IDs and verify that every available draft action is returned in order with localized hero names, acting side, team identities, professional names or explicit Steam32 account-ID fallbacks for picked heroes, patch, and match date.

**Acceptance Scenarios**:

1. **Given** a parsed professional match with complete draft and roster data, **When** an agent requests its draft, **Then** the response lists every pick and ban in chronological order and associates each picked hero with the professional name and account ID of the player who played it.
2. **Given** several valid match IDs, **When** an agent requests their drafts, **Then** the response preserves the requested match order and clearly separates the draft, Radiant team, Dire team, patch, date, and completeness status for each match.
3. **Given** a match for which a professional player name is unavailable but a Steam account ID is available, **When** the draft is requested, **Then** the picked hero identifies the player by that account ID and does not substitute a Steam profile name.
4. **Given** a match for which neither a professional player name nor Steam account ID is available, **When** the draft is requested, **Then** the player identity is explicitly marked as missing and is not inferred.
5. **Given** an unsupported optional field group, **When** an agent requests the draft, **Then** the request is rejected with the valid group names and no partial result is presented as complete.

---

### User Story 2 - Find Recent Tournament Matches (Priority: P2)

An analysis agent identifies a professional tournament by OpenDota league ID or by a tournament name query and retrieves its most recent matches, newest first, so it can select match IDs for draft inspection.

**Why this priority**: Tournament-scoped discovery enables analysis of an event meta, including ongoing events whose match list continues to grow.

**Independent Test**: Select a known professional league, request a bounded page of recent matches, and verify newest-first ordering, tournament identity, team sides, results, timestamps, match IDs, and usable continuation metadata.

**Acceptance Scenarios**:

1. **Given** a valid professional league ID with completed matches, **When** an agent requests the latest 10 matches, **Then** up to 10 matches are returned newest first with match ID, start time, Radiant and Dire identities, winner, and league identity.
2. **Given** a tournament name query that uniquely identifies a professional league, **When** an agent requests recent matches, **Then** the response identifies the resolved league and returns its match page.
3. **Given** a tournament name query matching multiple leagues, **When** an agent requests recent matches, **Then** the response asks the caller to choose from concise candidates and does not silently select a league.
4. **Given** an ongoing tournament, **When** the first page is requested again after new games are recorded, **Then** the newest available completed games appear first without changing the meaning of previously returned match IDs.
5. **Given** a tournament with more matches than fit on one page, **When** an agent follows continuation tokens until the terminal page, **Then** every eligible tournament match is obtainable without a fixed total-match ceiling and no page exceeds its requested size.

---

### User Story 3 - Find Recent Team Matches (Priority: P3)

An analysis agent identifies a professional team by stable OpenDota team ID or by name, retrieves its recent matches, and narrows them by date range, side, and team-relative win/loss result before selecting match IDs for draft analysis.

**Why this priority**: Team-specific filtering supports preparation and longitudinal analysis without forcing an agent to download and post-process a large history.

**Independent Test**: Find a known professional team by ID and by name, request its recent matches, and independently exercise name disambiguation, date, Radiant/Dire, win/loss, combined-filter, pagination, and no-result cases.

**Acceptance Scenarios**:

1. **Given** a valid professional team ID, **When** an agent requests recent matches without filters, **Then** a bounded newest-first page is returned with match ID, start time, opponent, team side, team-relative result, league identity, and score.
2. **Given** a team name or tag query that uniquely identifies a professional team, **When** an agent requests recent matches, **Then** the response identifies the resolved stable team ID and returns that team's match page.
3. **Given** a team name or tag query matching multiple teams, **When** an agent requests recent matches, **Then** the response returns concise candidates and requires explicit selection rather than silently choosing a team.
4. **Given** inclusive start and end dates, **When** an agent requests team matches, **Then** every returned match falls within the requested UTC date range.
5. **Given** a Radiant or Dire filter and a win or loss filter, **When** an agent requests team matches, **Then** every result satisfies both filters from the selected team's perspective.
6. **Given** valid filters with no matching games, **When** an agent requests team matches, **Then** an empty collection and terminal pagination metadata are returned rather than an error.
7. **Given** a team completes a new match during a paginated traversal, **When** an agent follows the existing continuation token, **Then** the traversal remains anchored to its first page and the new match appears only in a new traversal.

---

### User Story 4 - Run as a Local Analysis Service (Priority: P4)

A Codex user can install, configure, and start the project as a local MCP server, then discover and invoke all three analysis tools without editing source files.

**Why this priority**: The data capabilities must be usable through a local agent workflow, but this story can be validated after each core capability is independently complete.

**Independent Test**: Follow the repository's clean-environment setup instructions, register the server in a Codex-compatible MCP configuration, start it locally, list its tools, and complete one tournament/team search followed by one draft request.

**Acceptance Scenarios**:

1. **Given** a clean supported development environment, **When** a user follows the documented setup and startup instructions, **Then** the server starts locally with all dependencies and package metadata declared by the project.
2. **Given** a running local server, **When** Codex discovers its capabilities, **Then** the three tools expose unambiguous descriptions, bounded inputs, response-shaping options, and documented errors.
3. **Given** no OpenDota API key, **When** the user starts the server, **Then** public-access operation remains available with its applicable limits; when an optional key is configured, it is not returned in tool output or diagnostics.

### Edge Cases

- A request contains duplicate match IDs: silently return each distinct match once, in the position of its first occurrence; do not expose a duplicate-count or omitted-ID diagnostic.
- A request mixes valid, unavailable, non-professional, and not-yet-parsed match IDs: return per-match outcomes so valid records remain usable without presenting failed records as complete.
- OpenDota has picks/bans but lacks one or more player, team, league, patch-label, or localized hero-name records: preserve stable numeric IDs, use null for unavailable labels, and report precise completeness warnings.
- A professional name is missing: return the player's Steam32 account ID as the fallback identity; do not use the Steam profile name.
- A picked hero cannot be mapped uniquely to a player account: do not guess; report the player association as unavailable or ambiguous.
- Draft order values are absent, duplicated, or non-contiguous: preserve all received actions in upstream array sequence and mark the draft's ordering quality as degraded.
- A tournament name is blank, too broad, or has punctuation/casing variations: reject blank input, normalize harmless variations, prefer exact matches, and return ranked bounded substring candidates for broader queries.
- A team name/tag is blank, reused, renamed, or differs only by punctuation/casing: reject blank input, normalize harmless variations, prefer exact matches, and return ranked bounded substring candidates carrying stable IDs and recency context.
- A league exists but is amateur or has no eligible professional matches: explain the eligibility/no-data condition and return no match records.
- Team or league identity has changed names over time: use stable IDs as authoritative and preserve the match-time name when available.
- The selected team appears on neither or both sides of a match: exclude the anomalous record and report a data-quality warning.
- Date boundaries are reversed or malformed: reject the request with the expected date format; date boundaries are inclusive and interpreted in UTC.
- Page size is zero or above the maximum, or a continuation token is invalid/stale: reject it with valid bounds or restart guidance.
- A tournament or team gains matches during pagination: continuation pages remain anchored to the first page's dataset boundary; a new traversal is required to include the new matches.
- The upstream service throttles, times out, returns a server error, or returns malformed data: use bounded safe retries where applicable, honor caller cancellation/deadlines, and return a structured exhaustion or data-contract error when recovery is not possible.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The deliverable MUST provide a locally runnable, standards-compliant MCP server with declared project metadata, dependencies, supported runtime, startup entry point, and developer quality configuration sufficient for installation in a clean environment.
- **FR-002**: The repository MUST document local setup, optional OpenDota API-key configuration, startup, Codex-compatible registration, available tools, common invocations, limits, and troubleshooting without requiring source-code edits.
- **FR-003**: The server MUST expose exactly three initial public analysis capabilities: retrieve drafts by match IDs, list recent professional tournament matches, and list recent professional team matches.
- **FR-004**: Every tool MUST have a stable, descriptive name and description that tells an agent when to use it, its slim default response, supported filters or field groups, pagination or batch limits, and meaningful error outcomes.
- **FR-005**: The draft capability MUST accept an ordered collection of 1 to 10 match IDs, validate each ID, silently de-duplicate repeated IDs, and report results in first-occurrence request order. It MUST NOT expose a `duplicates_omitted` field or equivalent duplicate diagnostic.
- **FR-006**: For each successfully retrieved match, the draft capability's default response MUST include match ID; UTC start timestamp and calendar date; patch ID and human-readable patch version when available; Radiant and Dire team IDs and names; and a completeness status.
- **FR-007**: The draft capability MUST return every available draft action in chronological order with action order, pick/ban type, acting side, acting team ID/name, hero ID, and localized hero name.
- **FR-007a**: When all action-order values are valid, the draft capability MUST order actions by that authoritative value. If any value is missing, duplicated, or non-contiguous, it MUST preserve the entire upstream array sequence, retain the supplied order values where present, and mark ordering quality as `degraded` without claiming authoritative chronology.
- **FR-008**: For each pick, the draft capability MUST return the Steam32 account ID of the player who played that hero and the professional player name when available; bans MUST have no player association.
- **FR-009**: The draft capability MUST use the professional player name as the preferred display identity. When that name is missing, it MUST use the player's Steam32 account ID as the fallback display identity, MUST identify that fallback explicitly, and MUST NOT substitute the Steam profile name. If no account ID can be mapped unambiguously, player identity MUST be represented as unavailable or ambiguous.
- **FR-010**: The draft capability MUST support additive optional field groups: `competition` (league ID/name and series ID/type), `result` (winner, final scores, and duration), `draft_timing` (available timing per draft action), and `provenance` (retrieval time, source identity, upstream parse/version indicators, and warnings when present). Invalid group names MUST be rejected with valid choices.
- **FR-011**: The tournament capability MUST accept either a professional league ID or a tournament name query. Name matching MUST be case-insensitive and normalize harmless punctuation and spacing differences. It MUST prefer a unique normalized exact name match; otherwise it MUST return at most 10 ranked substring candidates and require explicit selection rather than silently choosing among multiple plausible leagues. Typo-tolerant fuzzy matching is out of scope.
- **FR-012**: The tournament capability MUST return eligible matches newest first. Its slim match record MUST include match ID, UTC start time, league ID/name, Radiant and Dire team IDs/names, winner, final score when available, and non-empty data-completeness warnings only when issues exist.
- **FR-013**: The team capability MUST accept either a professional team ID or a team name/tag query and MUST return matches newest first with match ID, UTC start time, league ID/name, resolved selected team ID/name, opponent ID/name, selected team's side, selected team's win/loss result, and final score when available.
- **FR-013a**: Team name/tag matching MUST be case-insensitive, normalize harmless punctuation and spacing differences, and search the available OpenDota team catalog. It MUST prefer a unique normalized exact name or tag match; otherwise it MUST return at most 10 ranked substring candidates and require explicit selection rather than silently choosing among multiple plausible teams. Typo-tolerant fuzzy matching is out of scope.
- **FR-014**: The team capability MUST support inclusive `start_date` and `end_date` filters in `YYYY-MM-DD` UTC form, a side filter of `radiant` or `dire`, and a team-relative result filter of `win` or `loss`; all supplied filters MUST combine using AND semantics.
- **FR-015**: Tournament and team match collections MUST use continuation-based pagination with a default page size of 20 and maximum of 100. Every response MUST include returned count, requested page size, a continuation token when more matching records are available, and an explicit terminal-page indicator.
- **FR-015a**: Tournament retrieval MUST impose no fixed maximum on the total number of eligible matches obtainable across pages. Pagination is an MCP-level contract and MUST remain available even when the selected upstream match source returns its collection without pagination.
- **FR-016**: Pagination MUST be deterministic, MUST NOT repeat or skip a match between adjacent pages within a traversal, and MUST reject invalid or mismatched continuation tokens rather than returning misleading results. Tournament and team continuation tokens MUST retain the dataset boundary established by their first page; matches added afterward MUST be excluded from that traversal and become visible when the caller starts again without a continuation token.
- **FR-017**: Collection tools MUST return an empty collection with terminal pagination metadata for a valid query with no matches; invalid identity, filter, eligibility, or pagination input MUST produce a structured actionable error.
- **FR-018**: Tool responses MUST use stable domain-oriented fields and MUST NOT expose unbounded raw upstream records. Unknown upstream fields MUST be ignored unless added later through a documented compatible field group.
- **FR-019**: All tools MUST preserve authoritative numeric identifiers alongside labels, use UTC ISO 8601 timestamps, distinguish absent data from false/zero values, and attach non-empty warnings to the affected record rather than only at response level. A `warnings` property MUST be absent when there are no warnings.
- **FR-020**: Public access without an API key MUST be supported where OpenDota permits it. An optional configured key MUST be treated as secret and MUST NOT appear in responses or diagnostics; OAuth is out of scope.
- **FR-021**: Safe read operations MUST absorb intermittent throttling, eligible timeouts, connection failures, and server failures using finite retries. A valid upstream retry delay MUST be honored only within the remaining retry budget and caller deadline; otherwise bounded increasing delay with jitter MUST be used.
- **FR-022**: Retries MUST stop on caller cancellation, deadline exhaustion, retry-budget exhaustion, unsafe or non-retryable errors, or an authoritative upstream instruction. The surfaced structured error MUST identify the affected tool/record, error category, retry exhaustion status, and whether a later retry may succeed without leaking secrets.
- **FR-023**: The local server MUST reserve standard output for MCP protocol traffic and direct diagnostics elsewhere so Codex and other compliant clients can communicate reliably.
- **FR-024**: Each public capability MUST have deterministic, offline-capable acceptance coverage for successful results, missing/partial data, validation, response groups, pagination boundaries, rate-limit recovery, retry exhaustion, non-retryable failures, and deadline/cancellation behavior.
- **FR-025**: Responses MUST use sparse diagnostics: omit `warnings` when there are no warnings, omit `error` when there is no error, and omit generic `status` for successful outcomes. A non-OK outcome MUST place its machine-actionable status inside the non-empty `warnings` or `error` diagnostic that explains the outcome. Substantive domain state such as completeness, ordering quality, result, and terminal pagination is unaffected.

### Scope Boundaries

**In scope**:

- Initial local project scaffold and user/developer documentation.
- Read-only professional match discovery by tournament or team.
- Read-only ordered pick/ban retrieval for explicitly supplied match IDs.
- Human-readable resolution of heroes, patches, teams, leagues, and professional players when authoritative data is available.
- Agent-context protection through bounded batches, focused filters, response groups, and pagination.

**Out of scope**:

- Predicting picks/bans, calculating draft scores, recommending heroes, or providing a user interface.
- Public matchmaking history, amateur-league analysis, live/in-progress draft tracking, replay parsing requests, or arbitrary data-explorer queries.
- Persisting match history, maintaining a private cache, or modifying OpenDota data.
- Inferring professional names, roles, draft intent, or missing pick/ban actions from unauthoritative sources.
- Remote hosting, multi-user access control, OAuth, or any write operation.

### Key Entities

- **Match Draft**: One professional match's stable match ID, time, patch, side assignments, ordered draft actions, optional competition/result context, and completeness status.
- **Draft Action**: An upstream ordering value, its source-array position, action type, hero, acting side/team, optional timing, and player association for picks only. The ordering value is authoritative when complete and valid; source-array position is the declared fallback for degraded ordering.
- **Professional Player**: Stable Steam32 account ID and optional professional display name associated with a picked hero; the account ID is the required fallback identity and is explicitly distinct from a Steam profile persona name.
- **Hero**: Stable hero ID and localized display name used in a draft action.
- **Professional Team**: Stable team ID and available match-time/display name, related to a match as Radiant, Dire, selected team, or opponent.
- **Tournament/League**: Stable OpenDota league ID, display name, professional eligibility, and associated matches.
- **Match Summary**: Compact discovery record containing identity, time, teams, competition, result, score, and warnings sufficient to choose match IDs.
- **Page**: A bounded collection response with query identity, returned count, page-size information, continuation token, and terminal status.
- **Data Warning**: Record-scoped description of missing, ambiguous, inconsistent, or partial upstream data that prevents silent inference.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fixture set of at least 20 complete professional matches, 100% of returned draft actions match the authoritative action type, hero, side, and chronological order, and 100% of picked heroes map to the correct available professional name or, when absent, the correct Steam32 account ID fallback.
- **SC-002**: For complete records, 100% of match responses identify the correct match ID, UTC date/time, patch, Radiant team, and Dire team; for incomplete records, 100% of unavailable required labels are explicitly marked rather than inferred.
- **SC-002a**: In fixtures with missing, duplicate, or non-contiguous draft-order values, 100% of actions retain their upstream array sequence and supplied order values, and 100% of affected drafts report degraded ordering quality.
- **SC-003**: Across tournament and team discovery fixtures, 100% of results are newest first, satisfy all requested filters, contain no duplicate or skipped match IDs across adjacent pages, and respect the requested/default page-size limit; terminal traversal yields 100% of eligible matches within the first page's dataset boundary, and newly added matches appear only in a new traversal.
- **SC-004**: An agent can find a tournament or team's recent match IDs and inspect at least one resulting draft in no more than two tool calls after the stable league/team ID is known, and no more than three calls when tournament- or team-name disambiguation is required.
- **SC-005**: Default output for a 20-match discovery page and for a single match draft contains no undocumented raw record sections and can be consumed without external file processing or command-line filtering.
- **SC-006**: In clean-environment acceptance testing, a user can install, register, start, and successfully invoke the local server from Codex in under 10 minutes by following repository documentation alone.
- **SC-007**: 100% of tested invalid inputs, ambiguous identities, unavailable records, partial data, and exhausted upstream failures return an actionable structured outcome without exposing secrets or misrepresenting partial data as complete.
- **SC-008**: All required offline quality checks and public-capability acceptance tests pass, and a protocol-level compatibility check confirms tool discovery and one successful end-to-end discovery-to-draft workflow.

## Assumptions

- OpenDota is the sole authoritative upstream data source for this feature; its documented public API currently permits unauthenticated access with lower limits and optional API-key access with higher limits.
- A "tournament" maps to an OpenDota league. The tournament tool supports ID-first retrieval plus bounded name resolution because agents may know a current event by name but stable IDs remain authoritative.
- A "professional match" is a match classified by OpenDota as professional or returned by its professional league/team data surfaces; amateur leagues are excluded from tournament match retrieval.
- "Last X" means a newest-first page after all filters are applied. The caller controls X through page size within the documented bound and follows continuation tokens for more results.
- Date filters apply to the match start timestamp in UTC and include the entire start and end calendar dates.
- Win/loss and side filters are interpreted from the requested team's perspective, not from Radiant's perspective.
- OpenDota's player `name` is the professional name, `account_id` is the Steam32 profile identifier, and `personaname` is the Steam profile name. The response prefers `name`, falls back to `account_id`, and never uses `personaname` as the display identity.
- OpenDota's team catalog exposes stable team IDs, team names, tags, and upstream pages. This makes MCP-side name/tag resolution feasible even though the documented team-match lookup itself is ID-based.
- The MCP server owns the caller-visible tournament pagination contract. If OpenDota returns all league matches at once, the server still exposes them as bounded pages with no fixed total-match limit.
- Human-readable patch versions may require resolving an OpenDota patch identifier against its published constants. When no mapping exists, the numeric patch ID remains available with a warning.
- Player roles/positions are useful for draft analysis but are excluded from the first version because authoritative match-time professional roles are not guaranteed by the documented match record. They can be considered in a later feature if a reliable source and semantics are established.
- The server is intended for local, single-user analytical workflows and read-only operation. Persistent storage and shared-user controls are unnecessary for this feature.
- The project constitution determines the approved language, framework, package manager, manifest format, test tools, lint tools, and minimum runtime during planning and implementation.

## Dependencies

- Continued availability and documented behavior of OpenDota match, professional league, team-match, professional-player, hero-constant, and patch-constant data.
- Availability of parsed match details for complete pick/ban and player-to-hero association data.
- A network connection from the locally running server to OpenDota during live use.
- A standards-compliant local MCP client; Codex is the required compatibility target.
