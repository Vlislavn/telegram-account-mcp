"""Local login and stdio MCP entry point."""

import argparse
import asyncio

from telegram_account_mcp.auth import login
from telegram_account_mcp.config import load_settings
from telegram_account_mcp.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Telegram account MCP")
    commands = parser.add_subparsers(dest="command", required=True)
    sign_in = commands.add_parser("login", help="Authorize a local Telegram session (QR by default)")
    sign_in.add_argument("--phone", action="store_true", help="Use phone/code instead of QR")
    commands.add_parser("serve", help="Start the stdio MCP server (run from an MCP host)")
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "login":
        asyncio.run(login(settings, method="phone" if args.phone else "qr"))
    else:
        create_server(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
