from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "stdio-super-secret"])
async def test_stdio_initialization_listing_invocation_and_clean_shutdown(
    api_key: str | None, tmp_path: Path
) -> None:
    log = tmp_path / "stderr.log"
    env = dict(os.environ)
    if api_key:
        env["OPENDOTA_API_KEY"] = api_key
    else:
        env.pop("OPENDOTA_API_KEY", None)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "open_dota_mcp"],
        cwd=str(Path(__file__).parents[2]),
        env=env,
        log_file=log,
    )
    async with Client(transport) as session:
        tools = await session.list_tools()
        assert len(tools) == 3
        result = await session.call_tool("get_pro_match_drafts", {"match_ids": []})
        assert result.structured_content["error"]["code"] == "invalid_match_ids"
    diagnostics = log.read_text() if log.exists() else ""
    assert not api_key or api_key not in diagnostics
