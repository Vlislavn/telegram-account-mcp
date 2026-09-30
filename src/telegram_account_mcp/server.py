"""Local, session-backed Telegram tools. No interactive login or persistent message store."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from datetime import time as Time
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User
from telethon.utils import get_peer_id

from telegram_account_mcp.config import Settings

MAX_DAYS_PER_QUERY = 31


def _dates(date: str | None, start_date: str | None, end_date: str | None) -> tuple[Date, Date, bool]:
    if (date is not None and (start_date is not None or end_date is not None)) or (
        date is None and (start_date is None or end_date is None)
    ):
        raise ValueError("Provide date or both start_date and end_date")

    def parse(value: str) -> Date:
        parsed = Date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Dates must be ISO YYYY-MM-DD")
        return parsed

    start = parse(date if date is not None else start_date)
    end = parse(date if date is not None else end_date)
    if start > end:
        raise ValueError("start_date must not exceed end_date")
    if (end - start).days >= MAX_DAYS_PER_QUERY:
        raise ValueError(f"Date range must cover at most {MAX_DAYS_PER_QUERY} days; split longer reads")
    return start, end, date is None


def _chat_type(dialog: Any) -> str:
    if getattr(dialog, "is_user", False):
        return "private"
    if getattr(dialog, "is_group", False) or getattr(getattr(dialog, "entity", None), "megagroup", False):
        return "group"
    if getattr(dialog, "is_channel", False):
        return "channel"
    return "unknown"


def _resolved_id(entity: Any) -> int:
    return get_peer_id(entity) if isinstance(entity, (User, Chat, Channel)) else int(entity.id)


def _message(msg: Any) -> dict[str, Any]:
    sender = getattr(msg, "sender", None)
    sender_name = (
        getattr(sender, "first_name", None)
        or getattr(sender, "title", None)
        or (
            "You"
            if getattr(msg, "out", False)
            else f"User {msg.sender_id}"
            if getattr(msg, "sender_id", None) is not None
            else "Unknown"
        )
    )
    return {
        "text": msg.text,
        "timestamp": msg.date.isoformat(),
        "message_id": msg.id,
        "outgoing": bool(getattr(msg, "out", False)),
        "sender_name": sender_name,
    }


def create_server(settings: Settings, *, client_factory=TelegramClient) -> FastMCP:
    """Register the read tools and, only when opted in, the send tool."""
    server = FastMCP("Telegram account")
    send_lock = asyncio.Lock()
    successful_sends: dict[tuple[int, str, int | None], float] = {}

    def permitted(chat_id: int) -> None:
        if settings.allowed_chat_ids is not None and chat_id not in settings.allowed_chat_ids:
            raise PermissionError("Chat is not in TELEGRAM_ALLOWED_CHAT_IDS")

    @asynccontextmanager
    async def connected():
        path = Path(settings.session_path)
        if not path.is_file():
            raise RuntimeError("Telegram session missing; log in before starting tools")
        session_stat = path.stat()
        if session_stat.st_mode & 0o077 or not hasattr(os, "getuid") or session_stat.st_uid != os.getuid():
            raise PermissionError("Telegram session must be owned by you and mode 0600; run chmod 600 on it")
        lock = FileLock(str(path) + ".lock", mode=0o600)
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("Telegram session in use") from exc
        client = None
        try:
            client = client_factory(str(path), settings.api_id, settings.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorized; log in first")
            yield client
        finally:
            try:
                if client is not None:
                    await client.disconnect()
            finally:
                lock.release()

    async def matching_dialogs(
        client: Any,
        chat_types: list[str] | None = None,
        private_allowlist_ids: list[int] | None = None,
        group_allowlist_ids: list[int] | None = None,
        group_allowlist_names: list[str] | None = None,
    ):
        if chat_types is not None and any(t not in {"private", "group", "channel"} for t in chat_types):
            raise ValueError("Unknown chat type")
        for ids in (private_allowlist_ids, group_allowlist_ids):
            for chat_id in ids or []:
                permitted(chat_id)
        names = {name.strip().casefold() for name in group_allowlist_names or []}
        if any(
            value is not None and not value
            for value in (chat_types, private_allowlist_ids, group_allowlist_ids, group_allowlist_names)
        ) or (group_allowlist_names is not None and not names):
            raise ValueError("Empty filters are not allowed")
        async for dialog in client.iter_dialogs():
            # Check the server boundary before touching history, even with name filters.
            if settings.allowed_chat_ids is not None and dialog.id not in settings.allowed_chat_ids:
                continue
            kind = _chat_type(dialog)
            if chat_types is not None and kind not in chat_types:
                continue
            if private_allowlist_ids is not None or group_allowlist_ids is not None or names:
                if not (
                    (kind == "private" and dialog.id in (private_allowlist_ids or []))
                    or (
                        kind == "group"
                        and (dialog.id in (group_allowlist_ids or []) or dialog.name.strip().casefold() in names)
                    )
                ):
                    continue
            yield dialog, kind

    async def range_messages(client: Any, chat_id: int, start: Date, end: Date):
        cursor = datetime.combine(end + timedelta(days=1), Time.min, tzinfo=timezone.utc) if end < Date.max else None
        async for msg in client.iter_messages(chat_id, offset_date=cursor):
            if msg is None or msg.date is None:
                continue
            day = msg.date.date()
            if day < start:
                break
            if day <= end and msg.text:
                yield msg

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def telegram_get_conversations(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        chat_types: list[str] | None = None,
        private_allowlist_ids: list[int] | None = None,
        group_allowlist_ids: list[int] | None = None,
        group_allowlist_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read text conversations on one date or an inclusive date range."""
        start, end, range_mode = _dates(date, start_date, end_date)
        days: dict[str, list[dict[str, Any]]] = {}
        current = start
        while current <= end:
            days[current.isoformat()] = []
            if current == end:
                break
            current += timedelta(days=1)
        async with connected() as client:
            async for dialog, kind in matching_dialogs(
                client, chat_types, private_allowlist_ids, group_allowlist_ids, group_allowlist_names
            ):
                by_day: dict[str, list[dict[str, Any]]] = {}
                async for msg in range_messages(client, dialog.id, start, end):
                    by_day.setdefault(msg.date.date().isoformat(), []).append(_message(msg))
                for day, messages in by_day.items():
                    days[day].append(
                        {
                            "chat_id": dialog.id,
                            "chat_name": dialog.name,
                            "chat_type": kind,
                            "messages": messages,
                            "message_count": len(messages),
                        }
                    )
        if not range_mode:
            return days[start.isoformat()]
        return [{"date": day, "chats": chats} for day, chats in days.items()]

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def get_sent_messages(date: str) -> list[dict[str, Any]]:
        """Read outgoing text messages on an ISO date."""
        day, _, _ = _dates(date, None, None)
        results = []
        async with connected() as client:
            async for dialog, _ in matching_dialogs(client):
                async for msg in range_messages(client, dialog.id, day, day):
                    if getattr(msg, "out", False):
                        results.append({**_message(msg), "chat_id": dialog.id, "chat_name": dialog.name})
        return results

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def telegram_get_chat_history(
        chat_id: int | str, limit: int = 50, before_msg_id: int | None = None
    ) -> dict[str, Any]:
        """Read newest-first text history by numeric ID or @username."""
        if isinstance(chat_id, str) and chat_id.lstrip("-").isdecimal():
            chat_id = int(chat_id)
        if isinstance(chat_id, int):
            permitted(chat_id)
        if limit < 1 or limit > 1000 or (before_msg_id is not None and before_msg_id < 1):
            raise ValueError("limit must be 1..1000 and before_msg_id must be positive")
        async with connected() as client:
            entity = await client.get_entity(chat_id)
            resolved_id = _resolved_id(entity)
            permitted(resolved_id)
            messages = []
            async for msg in client.iter_messages(entity, limit=limit, offset_id=before_msg_id or 0):
                from_id = getattr(msg, "from_id", None)
                messages.append(
                    {
                        "id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "from_id": getattr(from_id, "user_id", None),
                        "outgoing": bool(getattr(msg, "out", False)),
                        "text": msg.text or "",
                    }
                )
            return {
                "chat_id": resolved_id,
                "chat_name": getattr(entity, "title", None)
                or getattr(entity, "first_name", None)
                or getattr(entity, "username", None),
                "messages": messages,
            }

    if settings.enable_send:

        @server.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
            )
        )
        async def telegram_send_message(
            chat_id: int, text: str, reply_to_message_id: int | None = None
        ) -> dict[str, Any]:
            """Send one text message to an allowed chat; no automatic retries."""
            permitted(chat_id)
            if not text.strip():
                raise ValueError("text must not be empty")
            if reply_to_message_id is not None and reply_to_message_id < 1:
                raise ValueError("reply_to_message_id must be positive")
            key = (chat_id, text, reply_to_message_id)
            async with send_lock:
                now = time.monotonic()
                successful_sends_copy = {k: t for k, t in successful_sends.items() if now - t < 60}
                successful_sends.clear()
                successful_sends.update(successful_sends_copy)
                if key in successful_sends:
                    return {"status": "dedup_skipped", "chat_id": chat_id}
                async with connected() as client:
                    entity = await client.get_entity(chat_id)
                    permitted(_resolved_id(entity))
                    # Send to the checked entity, not an ambiguous cached integer ID.
                    # A failed or uncertain send is never recorded as successful or retried.
                    kwargs = {"reply_to": reply_to_message_id} if reply_to_message_id is not None else {}
                    try:
                        msg = await client.send_message(entity, text, **kwargs)
                    except Exception as exc:
                        return {"status": "unknown", "chat_id": chat_id, "error": type(exc).__name__}
                    successful_sends[key] = time.monotonic()
                    return {
                        "status": "sent",
                        "chat_id": chat_id,
                        "chat_name": getattr(entity, "title", None)
                        or getattr(entity, "first_name", None)
                        or str(chat_id),
                        "message_id": msg.id,
                        "text": text[:200],
                        "timestamp": msg.date.isoformat() if msg.date else None,
                        "error": None,
                    }

    return server
