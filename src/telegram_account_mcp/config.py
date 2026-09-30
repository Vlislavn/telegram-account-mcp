"""One local configuration boundary shared by the login CLI and MCP subprocess."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_path: Path
    allowed_chat_ids: frozenset[int] | None
    enable_send: bool


def load_settings() -> Settings:
    # MCP hosts may start in another directory; run with `uv --directory <checkout>`.
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    if not api_id.isdecimal() or int(api_id) <= 0 or not api_hash:
        raise ValueError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in this checkout's .env (see README)")

    raw_path = os.getenv("TELEGRAM_SESSION_PATH", "").strip()
    session_path = (
        Path(raw_path).expanduser()
        if raw_path
        else Path.home() / ".local" / "share" / "telegram-account-mcp" / "session.session"
    )
    if not session_path.is_absolute() or session_path.suffix != ".session":
        raise ValueError("TELEGRAM_SESSION_PATH must be an absolute path ending in .session")

    raw_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")
    if raw_ids is None:
        allowed_chat_ids = None
    else:
        parts = [part.strip() for part in raw_ids.split(",")]
        if not parts or any(not part or not part.lstrip("-").isdecimal() for part in parts):
            raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS must be comma-separated numeric IDs; unset to allow all")
        allowed_chat_ids = frozenset(int(part) for part in parts)

    raw_send = os.getenv("TELEGRAM_ENABLE_SEND", "0").strip().lower()
    if raw_send not in {"0", "1"}:
        raise ValueError("TELEGRAM_ENABLE_SEND must be 0 or 1")
    return Settings(int(api_id), api_hash, session_path, allowed_chat_ids, raw_send == "1")
