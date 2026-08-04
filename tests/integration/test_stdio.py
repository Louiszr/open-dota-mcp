from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.fixture
def offline_opendota() -> tuple[str, dict[str, int]]:
    """Serve a minimal deterministic OpenDota surface to the stdio subprocess."""
    state = {"calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            state["calls"] += 1
            path = self.path.split("?", 1)[0]
            payload: Any
            if path == "/api/teams/1":
                payload = {"team_id": 1, "name": "Radiant Pro"}
            elif path == "/api/constants/patch":
                payload = [{"id": 61, "name": "7.41", "date": 1782864000}]
            elif path == "/api/teams/1/matches":
                payload = [
                    {
                        "match_id": 2,
                        "start_time": 1784779201,
                        "duration": 1200,
                        "radiant_team_id": 1,
                        "dire_team_id": 2,
                        "radiant_team_name": "Radiant Pro",
                        "dire_team_name": "Dire Pro",
                        "radiant_win": True,
                    },
                    {
                        "match_id": 1,
                        "start_time": 1784779200,
                        "duration": 1200,
                        "radiant_team_id": 1,
                        "dire_team_id": 2,
                        "radiant_team_name": "Radiant Pro",
                        "dire_team_name": "Dire Pro",
                        "radiant_win": True,
                    },
                ]
            elif path == "/api/teams/1/players" or path == "/api/players/101/matches":
                payload = []
            elif path == "/api/leagues":
                payload = [{"leagueid": 10, "name": "Premier Cup", "tier": "premium"}]
            elif path == "/api/leagues/10/matches":
                payload = [{"match_id": 1, "start_time": 1784779200, "leagueid": 10}]
            elif path == "/api/heroes":
                payload = []
            elif path == "/api/proPlayers":
                payload = [{"account_id": 101, "name": "Example"}]
            elif path in {"/api/matches/1", "/api/matches/2"}:
                match_id = int(path.rsplit("/", 1)[1])
                payload = {
                    "match_id": match_id,
                    "version": 21,
                    "start_time": 1784779200 + match_id,
                    "duration": 1200,
                    "patch": 61,
                    "leagueid": 10,
                    "radiant_team_id": 1,
                    "radiant_name": "Radiant Pro",
                    "dire_team_id": 2,
                    "dire_name": "Dire Pro",
                    "radiant_win": True,
                    "picks_bans": [],
                    "players": [],
                }
            else:
                self.send_error(404)
                return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "stdio-super-secret"])
@pytest.mark.parametrize("entrypoint", ["module", "console"])
async def test_stdio_initialization_listing_invocation_and_clean_shutdown(
    api_key: str | None,
    entrypoint: str,
    tmp_path: Path,
    offline_opendota: tuple[str, dict[str, int]],
) -> None:
    log = tmp_path / "stderr.log"
    env = dict(os.environ)
    if api_key:
        env["OPENDOTA_API_KEY"] = api_key
    else:
        env.pop("OPENDOTA_API_KEY", None)
    env["OPENDOTA_CACHE_DIR"] = str(tmp_path / "cache")
    env["OPENDOTA_BASE_URL"] = offline_opendota[0]
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
        assert len(tools) == 6
        resources = await session.list_resources()
        assert len(resources) == 1
        scoring = await session.read_resource("opendota://fantasy/ti-2026/scoring")
        scoring_text = scoring[0].text if isinstance(scoring, list) else scoring.text
        assert json.loads(scoring_text)["edition"] == "ti-2026-v1"
        result = await session.call_tool("get_pro_match_drafts", {"match_ids": []})
        assert result.structured_content["error"]["code"] == "invalid_match_ids"
        tournament = await session.call_tool("list_pro_tournament_matches", {"league_id": 10})
        assert tournament.structured_content["matches"][0]["match_id"] == 1
        team = await session.call_tool("list_pro_team_matches", {"team_id": 1})
        assert team.structured_content["matches"][0]["match_id"] == 2
        fantasy = await session.call_tool("get_pro_player_fantasy", {"account_id": 101})
        assert fantasy.structured_content["matches"] == []
        roster = await session.call_tool("get_pro_team_roster", {"team_id": 1})
        assert roster.structured_content["error"]["code"] == "current_roster_unavailable"
        first = await session.call_tool("analyze_pro_team_drafts", {"team_id": 1, "page_size": 1})
        cursor = first.structured_content["next_cursor"]
        calls = offline_opendota[1]["calls"]
        final = await session.call_tool("analyze_pro_team_drafts", {"continuation_cursor": cursor})
        assert len(final.structured_content["matches"]) == 1
        assert "next_cursor" not in final.structured_content
        assert offline_opendota[1]["calls"] == calls
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
