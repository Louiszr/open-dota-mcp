from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "stdio-super-secret"])
@pytest.mark.parametrize("entrypoint", ["module", "console"])
async def test_stdio_initialization_listing_invocation_and_clean_shutdown(
    api_key: str | None, entrypoint: str, tmp_path: Path
) -> None:
    log = tmp_path / "stderr.log"
    env = dict(os.environ)
    if api_key:
        env["OPENDOTA_API_KEY"] = api_key
    else:
        env.pop("OPENDOTA_API_KEY", None)
    env["OPENDOTA_CACHE_DIR"] = str(tmp_path / "cache")
    command = (
        sys.executable
        if entrypoint == "module"
        else str(Path(sys.executable).with_name("open-dota-mcp"))
    )
    args = ["-m", "open_dota_mcp"] if entrypoint == "module" else []
    transport = StdioTransport(
        command=command,
        args=args,
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


@pytest.mark.parametrize("entrypoint", ["module", "console"])
def test_cache_subcommands_are_standalone_and_keep_diagnostics_separate(
    entrypoint: str, tmp_path: Path
) -> None:
    env = dict(os.environ)
    env["OPENDOTA_CACHE_DIR"] = str(tmp_path / "cache")
    if entrypoint == "module":
        command = [sys.executable, "-m", "open_dota_mcp"]
    else:
        command = [str(Path(sys.executable).with_name("open-dota-mcp"))]
    root = Path(__file__).parents[2]
    info = subprocess.run(
        [*command, "cache", "info", "--json"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert info.returncode == 0 and info.stderr == ""
    assert json.loads(info.stdout)["entry_count"] == 0
    entries = subprocess.run(
        [*command, "cache", "entries", "--json"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert entries.returncode == 0 and json.loads(entries.stdout)["returned_count"] == 0
    clear = subprocess.run(
        [*command, "cache", "clear", "--yes", "--json"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert clear.returncode == 0 and json.loads(clear.stdout)["generation"] == 1
