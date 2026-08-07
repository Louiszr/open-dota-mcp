"""Installed, network-free MCP resource loading."""

from __future__ import annotations

from importlib.resources import files

from open_dota_mcp.fantasy_rules import validate_scoring_reference


def load_ti_2026_scoring() -> str:
    """Load and validate the installed TI 2026 scoring JSON document."""
    content = files(__package__).joinpath("ti_2026_fantasy.json").read_text(encoding="utf-8")
    validate_scoring_reference(content)
    return content
