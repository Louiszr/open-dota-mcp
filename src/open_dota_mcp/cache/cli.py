"""Standalone cache inspection and confirmed-removal CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from open_dota_mcp.cache.store import CacheStore
from open_dota_mcp.config import Settings


def run_cache_cli(argv: Sequence[str], *, settings: Settings | None = None) -> int:
    """Run one explicit cache management command.

    Args:
        argv: Arguments following the ``cache`` command.
        settings: Optional validated runtime settings.

    Returns:
        Process-style exit status.
    """
    parser = _parser()
    try:
        args = parser.parse_args(list(argv))
        runtime = settings or Settings.from_env()
        store = CacheStore(runtime.cache_dir, runtime.cache_max_bytes)
        if args.command == "info":
            _render(asdict(store.info()), args.json)
        elif args.command == "entries":
            page = store.entries(
                operation=args.operation,
                category=args.category,
                limit=args.limit,
                cursor=args.cursor,
            )
            payload: dict[str, Any] = asdict(page)
            payload["entries"] = list(payload["entries"])
            _render(payload, args.json)
        elif args.command == "clear":
            if not args.yes:
                parser.error("cache clear requires --yes; no state was changed")
            _render(asdict(store.clear()), args.json)
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except ValueError as exc:
        print(f"cache usage error: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"cache error: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-dota-mcp cache")
    commands = parser.add_subparsers(dest="command", required=True)
    info = commands.add_parser("info")
    info.add_argument("--json", action="store_true")
    entries = commands.add_parser("entries")
    entries.add_argument("--operation")
    entries.add_argument("--category", choices=("short", "long"))
    entries.add_argument("--limit", type=int, default=50)
    entries.add_argument("--cursor")
    entries.add_argument("--json", action="store_true")
    clear = commands.add_parser("clear")
    clear.add_argument("--yes", action="store_true")
    clear.add_argument("--json", action="store_true")
    return parser


def _render(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return
    for key, value in payload.items():
        if key == "entries":
            for entry in value:
                print(json.dumps(entry, separators=(",", ":"), sort_keys=True))
        else:
            print(f"{key}: {value}")
