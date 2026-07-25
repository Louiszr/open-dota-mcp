"""Protocol-only stdio module entry point."""

from open_dota_mcp.server import mcp


def main() -> None:
    """Run the local MCP server over stdio without a stdout banner."""
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
