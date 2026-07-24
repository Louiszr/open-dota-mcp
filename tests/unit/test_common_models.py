from __future__ import annotations

from open_dota_mcp.errors import DataWarning, ErrorResponse, ToolErrorDetail, validation_error
from open_dota_mcp.models.common import (
    PageMetadata,
    TeamIdentity,
    WarningCollection,
    utc_datetime,
    utc_iso,
)
from open_dota_mcp.models.drafts import DraftOutcome


def test_sparse_success_omits_empty_diagnostics_but_keeps_zero_false() -> None:
    page = PageMetadata(returned_count=0, page_size=20, terminal=True)
    assert page.model_dump() == {
        "returned_count": 0,
        "page_size": 20,
        "continuation_token": None,
        "terminal": True,
        "snapshot_expires_at": None,
    }
    assert TeamIdentity(team_id=1, name=None).model_dump()["name"] is None


def test_sparse_failure_has_nested_status_and_no_null_outcome() -> None:
    outcome = DraftOutcome(
        match_id=1,
        error=ToolErrorDetail(code="unavailable", message="gone", tool="draft"),
    ).model_dump()
    assert "draft" not in outcome
    assert outcome["error"]["status"] == "error"
    assert "status" not in outcome


def test_warning_and_error_models_serialize_safely() -> None:
    warning = DataWarning(code="missing_score", message="score absent")
    error = ErrorResponse(error=ToolErrorDetail(code="bad", message="safe", tool="team"))
    assert warning.model_dump()["status"] == "warning"
    assert error.model_dump()["error"]["retry_exhausted"] is False


def test_public_diagnostic_helpers_omit_inactive_fields() -> None:
    response = validation_error("team", "invalid_filter", "bad side", valid_values=["dire"])
    assert response.model_dump()["error"]["valid_values"] == ["dire"]
    assert WarningCollection().model_dump() == {}


def test_utc_helpers_preserve_epoch_zero() -> None:
    value = utc_datetime(0)
    assert value is not None
    assert utc_iso(value) == "1970-01-01T00:00:00Z"
