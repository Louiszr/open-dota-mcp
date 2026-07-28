"""Protocol-only stdio and explicit cache-management entry point."""

import sys

from open_dota_mcp.cache.cli import run_cache_cli
from open_dota_mcp.server import mcp


def main() -> None:
    """Run stdio by default or dispatch an explicit cache subcommand."""
    if len(sys.argv) > 1:
        if sys.argv[1] == "cache":
            raise SystemExit(run_cache_cli(sys.argv[2:]))
        print("usage: open-dota-mcp [cache {info,entries,clear}]", file=sys.stderr)
        raise SystemExit(2)
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
