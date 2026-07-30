"""Sparse diagnostics and safe upstream exception mapping."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WarningStatus(StrEnum):
    """Non-success warning states."""

    WARNING = "warning"
    NEEDS_SELECTION = "needs_selection"


class ErrorStatus(StrEnum):
    """Machine-actionable failure states."""

    ERROR = "error"
    UNAVAILABLE = "unavailable"
    NOT_PROFESSIONAL = "not_professional"
    NOT_PARSED = "not_parsed"
    UPSTREAM_ERROR = "upstream_error"


class SparseModel(BaseModel):
    """Base model whose public serialization omits absent and empty optional data."""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)


def omit_none(value: object) -> bool:
    """Return whether an inactive optional union property should be omitted."""
    return value is None


def omit_none_or_empty(value: object) -> bool:
    """Return whether an optional diagnostic collection should be omitted."""
    return value is None or value == []


class DataWarning(SparseModel):
    """A localized, non-empty data-quality or selection diagnostic."""

    status: WarningStatus = WarningStatus.WARNING
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    path: str | None = Field(default=None, exclude_if=omit_none)


class ToolErrorDetail(SparseModel):
    """A secret-safe structured tool failure."""

    status: ErrorStatus = ErrorStatus.ERROR
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    target: str | None = Field(default=None, exclude_if=omit_none)
    retry_exhausted: bool = False
    retryable_later: bool = False
    valid_values: list[str] | None = Field(default=None, exclude_if=omit_none_or_empty)
    restart_required: bool | None = Field(default=None, exclude_if=omit_none)
    reason: str | None = Field(default=None, exclude_if=omit_none)
    retry_after_seconds: float | None = Field(default=None, gt=0, exclude_if=omit_none)


class AnalysisErrorDetail(SparseModel):
    """Minimal stable error contract for the drafting analysis tool."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    valid_values: list[str] | None = Field(default=None, exclude_if=omit_none_or_empty)
    restart_required: bool | None = Field(default=None, exclude_if=omit_none)
    reason: str | None = Field(default=None, exclude_if=omit_none)
    retry_after_seconds: float | None = Field(default=None, gt=0, exclude_if=omit_none)


class ErrorResponse(SparseModel):
    """Top-level sparse error envelope."""

    error: ToolErrorDetail


class UpstreamError(RuntimeError):
    """A classified and sanitized failure from OpenDota."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_exhausted: bool = False,
        retryable_later: bool = False,
        status_code: int | None = None,
        reason: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Create an upstream error without retaining request credentials.

        Args:
            code: Stable public error code.
            message: Sanitized human-readable message.
            retry_exhausted: Whether all safe attempts were consumed.
            retryable_later: Whether a later call may succeed.
            status_code: Optional HTTP status, retained only as an integer.
            reason: Optional stable retry exhaustion reason.
            retry_after_seconds: Optional safe actionable upstream delay.
        """
        super().__init__(message)
        self.code = code
        self.retry_exhausted = retry_exhausted
        self.retryable_later = retryable_later
        self.status_code = status_code
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds

    def detail(
        self,
        tool: str,
        *,
        target: str | None = None,
        status: ErrorStatus = ErrorStatus.ERROR,
    ) -> ToolErrorDetail:
        """Convert this exception into a public diagnostic.

        Args:
            tool: MCP tool that encountered the failure.
            target: Optional affected identifier.
            status: Domain-specific failure status.

        Returns:
            A sparse, secret-free error detail.
        """
        return ToolErrorDetail(
            status=status,
            code=self.code,
            message=str(self),
            tool=tool,
            target=target,
            retry_exhausted=self.retry_exhausted,
            retryable_later=self.retryable_later,
            reason=self.reason,
            retry_after_seconds=self.retry_after_seconds,
        )

    def analysis_detail(self) -> AnalysisErrorDetail:
        """Convert this exception into the lean analysis error contract."""
        return AnalysisErrorDetail(
            code=self.code,
            message=str(self),
            reason=self.reason,
            retry_after_seconds=self.retry_after_seconds,
        )


def validation_error(
    tool: str,
    code: str,
    message: str,
    *,
    target: str | None = None,
    valid_values: list[str] | None = None,
    restart_required: Literal[True] | None = None,
) -> ErrorResponse:
    """Build a consistent structured validation failure.

    Args:
        tool: Public tool name.
        code: Stable error code.
        message: Actionable explanation.
        target: Invalid input name or value.
        valid_values: Optional valid choices.
        restart_required: Whether the caller must begin a new traversal.

    Returns:
        Sparse top-level error response.
    """
    return ErrorResponse(
        error=ToolErrorDetail(
            code=code,
            message=message,
            tool=tool,
            target=target,
            valid_values=valid_values,
            restart_required=restart_required,
        )
    )
