# QA Report: Professional Draft Analysis MCP

## Timed clean-environment acceptance (T046)

- Date: 2026-07-23
- Host: macOS Apple Silicon
- Runtime: clean uv-managed CPython 3.13.12 virtual environment
- Package cache: newly created empty directory
- Tools: uv 0.10.12, Codex CLI 0.145.0, FastMCP 3.4.4, MCP 1.28.1
- Elapsed wall time: 16 seconds (requirement: under 10 minutes)
- Result: PASS

Commands and steps:

1. `uv venv <temporary-directory>/.venv --python 3.13`
2. `uv pip install --python <temporary-directory>/.venv/bin/python -e .`
3. `codex mcp add open-dota-success-acceptance -- <temporary-python> -m open_dota_mcp`
4. `codex mcp list` confirmed the registered stdio server was enabled.
5. `codex exec --ephemeral --sandbox read-only ...` invoked
   `get_pro_match_drafts` with current professional match ID `8910670427` through MCP.
6. OpenDota returned a successful parsed professional draft; Codex reported
   `{"match_id":8910670427,"draft_present":true}`.
7. `codex mcp remove open-dota-success-acceptance` removed the temporary registration.

The run started with no project virtual environment or dependency cache at the
temporary paths. Installation downloaded and installed 67 runtime packages. The MCP
tool call completed through Codex without shell fallback, returned a successful domain
object rather than a validation result, and the temporary global registration was
cleaned up afterward.

## Implementation verification before independent QA

- Typed FastMCP inspection: PASS; exactly three tools, no prompts/resources, expanded
  object output schemas, stable descriptions, standard read-only annotations.
- Public type/docstring AST audit: PASS after remediation.
- Ruff lint: PASS.
- Ruff format: PASS.
- Offline pytest suite: PASS (63 tests after the endpoint-shape regression fixes).

## Independent QA (T047)

First independent review by `/root/independent_qa` found missing per-capability
retry/error/cancellation/deadline acceptance coverage and rejected the original Codex
validation-only invocation. Remediation added tool/service contract coverage for all
three capabilities, explicit caller-deadline tests, public diagnostic-helper coverage,
and the successful live Codex invocation recorded above.

Final independent rerun by `/root/independent_qa`: **PASS**.

- Required-test review: PASS; no missing public-surface or risk-based tests found.
- `UV_CACHE_DIR=/private/tmp/open-dota-mcp-independent-qa-rerun uv run ruff check .`:
  exit 0, all checks passed.
- `UV_CACHE_DIR=/private/tmp/open-dota-mcp-independent-qa-rerun uv run ruff format --check .`:
  exit 0, 55 files already formatted.
- `UV_CACHE_DIR=/private/tmp/open-dota-mcp-independent-qa-rerun uv run pytest`:
  exit 0, 61 tests passed in 1.89 seconds.
- T045 public API type/docstring audit: PASS.
- T046 clean-cache timed successful Codex domain invocation: PASS.

The unprefixed `uv run` attempt could not access the agent sandbox's default uv cache;
the independent rerun therefore used a fresh private cache under `/private/tmp` without
changing any project dependency or test behavior.

## Endpoint-shape remediation QA (T048)

Independent final review by `/root/independent_qa`: **PASS**.

- Required-test review: PASS. Compact team-match coverage directly asserts selected side and
  opponent ID/name; league-match coverage directly asserts the route-specific team-name fields;
  patch coverage directly asserts that ID `0` resolves to `6.70`; compatibility coverage for
  the previously accepted full-side team shape remains.
- Endpoint research review: PASS. Official source and independent live samples confirmed the
  documented top-level shapes and consumed fields for all nine endpoints.
- `uv run ruff check .`: exit 0, all checks passed.
- `uv run ruff format --check .`: exit 0, 55 files already formatted.
- `uv run pytest`: exit 0, 63 tests passed in 1.93 seconds.
