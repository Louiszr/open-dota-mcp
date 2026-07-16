<!--
Sync Impact Report
==================
- Version change: 1.1.0 → 1.2.0
  (MINOR — materially expands agent-friendly MCP response design mandates)
- Modified principles:
  - VII. Standards-Based MCP Interoperability → Agent-Friendly, Standards-Based
    MCP Interoperability
  - IV. Risk-Based Testing Discipline → expanded with response-shaping and
    pagination contract coverage
  - Development Workflow → expanded with agent-ergonomics design and review gates
- Added sections: none
- Removed sections: none
- Templates and runtime guidance requiring updates:
  - .specify/templates/plan-template.md ✅ updated
  - .specify/templates/spec-template.md ✅ updated
  - .specify/templates/tasks-template.md ✅ updated
  - .agents/skills/speckit-plan/SKILL.md ✅ updated
  - .agents/skills/speckit-tasks/SKILL.md ✅ updated
  - Other installed .agents/skills/speckit-*/SKILL.md commands ✅ no changes needed
  - .specify/templates/checklist-template.md ✅ no changes needed
  - .specify/templates/constitution-template.md ✅ no changes needed
  - Runtime guidance (README.md, docs/, AGENTS.md) ✅ none present
- Follow-up TODOs: none
-->

# open-dota-mcp Constitution

## Core Principles

### I. YAGNI & Start Small

- Every feature MUST solve an immediate, demonstrated need. Do not build for
  hypothetical future requirements.
- Implement the smallest useful MCP surface first. Extend it only when a concrete
  user scenario demands more behavior.
- Three similar lines of code are preferable to a premature abstraction.
- Feature flags, compatibility shims, caches, and speculative configurability MUST
  NOT be added unless a current requirement justifies them.

### II. Type Safety & Documentation

- All function signatures MUST be fully typed, using explicit parameter and return
  types and precise generic parameters such as `dict[str, list[str]]`.
- Every public function, public class, and MCP tool MUST have a Google-style
  docstring describing arguments, returns, and raised errors where applicable.
- Internal helpers SHOULD have at least a one-line docstring unless their purpose is
  completely expressed by their name and type signature.
- MCP tool descriptions and input schemas MUST state behavior clearly enough for an
  agent to select and invoke the tool without harness-specific prompt guidance.

### III. OpenDota API Compliance

- Before implementing an OpenDota API interaction, the developer MUST consult the
  official OpenDota documentation to verify endpoint behavior, query parameters,
  request and response schemas, authentication requirements, and rate limits.
- API wrappers MUST faithfully reflect documented OpenDota contracts. They MUST NOT
  invent parameters, fields, guarantees, or behaviors absent from the official API.
- OAuth MUST NOT be introduced unless OpenDota's official documentation later makes
  it necessary for an implemented capability. If an API key is supported or required,
  it MUST be supplied through configuration, excluded from logs and source control,
  and granted no broader access than needed.
- Rate limits, pagination, missing data, non-success responses, timeouts, and upstream
  schema variation MUST be handled explicitly wherever the selected endpoint can
  expose them.
- MCP tools that call upstream APIs MUST absorb intermittent rate-limit failures when
  safe. For HTTP 429 responses, clients MUST honor a valid `Retry-After` value when
  it fits within the configured retry budget and caller deadline. An invalid value
  MUST fall back to bounded, increasing backoff with jitter. If the requested delay
  exceeds the available budget, the client MUST stop retrying and surface exhaustion.
- Other transient failures documented or classified as retryable, such as eligible
  timeouts, connection failures, and server errors, MUST be retried with the same
  bounded policy when the operation is safe to repeat.
- A retryable upstream error MUST NOT be surfaced to the MCP caller until the retry
  budget is exhausted or another attempt would violate caller cancellation, deadline,
  operation safety, or an authoritative upstream instruction. Attempt count,
  individual delay, and total elapsed retry limits MUST be finite and configurable
  to prevent unbounded latency and retry storms.

### IV. Risk-Based Testing Discipline

- Every public-facing Python function and every MCP tool MUST have corresponding
  pytest tests covering its documented success behavior and meaningful failure cases.
- Tests for those public surfaces MUST be written before or alongside implementation;
  they MUST NOT be deferred to a later feature.
- Tests for private and internal code are required when justified by risk or
  complexity. The plan and review MUST consider tests for branching logic, parsing,
  transformations, error recovery, regressions, and code that is difficult to verify
  adequately through its public surface. Trivial internal delegation does not require
  a dedicated test.
- External API calls in automated tests MUST be mocked, stubbed, or served by a local
  fixture so the default test suite remains deterministic and offline-capable.
- API-facing MCP tool tests MUST cover successful retry recovery, exhausted retry
  budgets, `Retry-After` handling, and non-retryable failures without real delays.
- MCP tool contract tests MUST cover the slim default response, every supported
  response field group, invalid group selections, and pagination boundaries where
  those capabilities apply.
- Shared setup SHOULD use pytest fixtures, and test data MUST be explicit rather than
  hidden in unexplained magic values.

### V. Code Quality & Linting

- All Python code MUST pass Ruff linting and formatting checks with zero violations
  before merge.
- Ruff configuration MUST be defined in `pyproject.toml`, including import sorting.
- Suppressions MUST be narrow and carry a concrete rationale when the reason is not
  self-evident.

### VI. High Information Density Code

- Code MUST make intent and data flow explicit at the point of use.
- Comprehensions, generator expressions, and focused transformations SHOULD be used
  when they are clearer than loops with mutable accumulators.
- Mutable intermediate state MUST be avoided when a short, readable transformation
  can express the same behavior without hidden side effects.
- Complex branching, early exits, and performance-sensitive paths MAY use imperative
  control flow when it is clearer. Readability and diagnosability take precedence over
  forcing a functional style.
- Long or mutation-heavy loop bodies SHOULD be extracted into well-named, typed
  helpers when doing so makes the operation easier to understand and test.

### VII. Agent-Friendly, Standards-Based MCP Interoperability

- Tools, resources, schemas, errors, and transports MUST conform to the MCP standard
  and FastMCP's documented contracts; they MUST NOT rely on undocumented behavior of
  a single client or agent harness.
- Codex is a required compatibility target. Each public MCP capability MUST be
  validated through a Codex-compatible MCP configuration or an equivalent
  protocol-level integration test before release.
- The server MUST remain usable by other standards-compliant MCP harnesses. Any known
  harness-specific limitation MUST be documented, narrowly isolated, and justified.
- Standard output MUST remain reserved for MCP protocol traffic when using stdio;
  diagnostics MUST use standard error or the framework's logging facilities.
- Tool names, descriptions, parameters, returned content, and errors MUST be stable,
  unambiguous, and useful to both agents and human MCP client developers.
- MCP tools MUST return a small, useful core response by default. A tool that can
  return a rich or large record MUST, when technically applicable, expose a stable
  caller-controlled selector such as `include` for opting into documented groups of
  semantically related fields, for example
  `include=["heroes", "player_details", "teamfight"]`. The MCP design and interface
  contract MUST define each group and its fields. Groups MUST be cohesive,
  independently selectable, and additive to the core response.
- If caller-controlled response shaping is not technically applicable to a rich or
  large response, the implementation plan MUST document the reason and the bounded
  alternative used to protect agent context. Arbitrary raw upstream field selection
  MUST NOT replace stable, domain-oriented groups unless the contract can preserve
  validation and compatibility.
- Tools returning collections with unbounded cardinality MUST use pagination. Page
  size MUST have a documented default and maximum, and responses MUST expose
  sufficient cursor or page metadata for an agent to request the next page without
  replaying or parsing unrelated data.
- Tools MUST expose focused lookup, filter, or field-group parameters when a focused
  retrieval scenario identified in the feature specification would otherwise require
  a large payload to obtain a small result. An agent MUST NOT need to write a response
  to a file, invoke `jq`, or process a large JSON document merely to complete such a
  scenario.
- Tool descriptions MUST explain the slim default, available response groups,
  pagination controls, limits, and relevant combinations so an agent can choose an
  efficient response shape before invoking the tool.
- These constraints preserve broad tool usefulness while protecting limited agent
  context from irrelevant data and avoidable post-processing.

## Technology Stack

- **Language**: Python 3.13+
- **MCP Framework**: FastMCP
- **Package Manager**: uv
- **Importable Package Name**: `open_dota_mcp`
- **HTTP Client**: httpx with asynchronous request support
- **Testing**: pytest with pytest-asyncio for asynchronous tests
- **Linting & Formatting**: Ruff
- **Type Checking**: fully typed signatures enforced by convention and review
- **Primary Compatibility Target**: Codex, without sacrificing standard MCP client
  compatibility

## Development Workflow

- All dependencies MUST be managed through uv and declared in `pyproject.toml`.
- The project MUST be installable with `uv pip install -e .` for local development.
- Plans MUST include a Constitution Check covering OpenDota contract research, required
  public-surface tests, code-quality gates, agent-friendly response shaping and
  pagination, and MCP/Codex interoperability.
- CI MUST run `ruff check`, `ruff format --check`, and the complete pytest suite.
- Changes to a public MCP tool MUST include or update its tests and user-facing schema
  or documentation in the same change.
- MCP tool design and review MUST demonstrate that common focused tasks fit in a
  bounded response, that optional field groups are semantically cohesive, and that
  potentially large collections can be consumed incrementally.
- Before `/speckit-implement` reports completion, an independent QA sub-agent that did
  not implement the change MUST verify that all required public-surface and risk-based
  tests are present, then run Ruff linting, Ruff format checking, and the complete
  pytest suite. Completion MUST NOT be reported unless every check passes.
- If independent QA finds a failure, the implementing agent MUST remediate it and the
  independent QA sub-agent MUST re-run all affected checks before completion.
- Commits SHOULD be atomic and focused on one logical change.
- Branch names SHOULD follow `<type>/<short-description>`, such as
  `feat/list-matches` or `fix/rate-limit-error`.

## Governance

- This constitution supersedes conflicting development practices in the
  open-dota-mcp repository.
- Amendments require a documented rationale, a semantic version bump, an updated
  Last Amended date, and synchronization of affected templates and runtime guidance.
- Version changes follow semantic versioning: MAJOR for incompatible governance or
  principle redefinitions, MINOR for new principles or materially expanded mandates,
  and PATCH for non-semantic clarifications.
- Every implementation plan and code review MUST verify compliance with all applicable
  MUST rules. Reviewers MUST reject unexplained violations.
- Complexity or exceptions beyond these rules MUST be justified in the relevant plan
  and pull request. An exception does not amend the constitution or establish precedent.
- Compliance MUST be re-evaluated when plans change and before a release is merged.

**Version**: 1.2.0 | **Ratified**: 2026-07-15 | **Last Amended**: 2026-07-15
