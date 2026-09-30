"""Protocol-level tests; fake Telethon client never touches the network."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from telegram_account_mcp.config import Settings
from telegram_account_mcp.server import create_server

STAMP = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, session, api_id, api_hash, *, authorized=True):
        self.authorized = authorized
        self.sent = []
        self.connected = 0
        self.disconnected = 0
        self.scanned = []
        self.entity_override = None
        self.dialogs = [
            SimpleNamespace(id=1, name="Alice", is_user=True, is_group=False, is_channel=False, entity=None),
            SimpleNamespace(id=2, name="Team", is_user=False, is_group=True, is_channel=False, entity=None),
        ]
        self.messages = {
            1: [
                SimpleNamespace(
                    id=9,
                    text="hello",
                    date=STAMP,
                    out=True,
                    sender_id=1,
                    sender=None,
                    from_id=SimpleNamespace(user_id=1),
                ),
                SimpleNamespace(
                    id=8,
                    text="yesterday",
                    date=STAMP.replace(day=1),
                    out=False,
                    sender_id=3,
                    sender=None,
                    from_id=SimpleNamespace(user_id=3),
                ),
            ],
            2: [SimpleNamespace(id=7, text="secret", date=STAMP, out=True, sender_id=4, sender=None, from_id=None)],
        }

    async def connect(self):
        self.connected += 1

    async def is_user_authorized(self):
        return self.authorized

    async def disconnect(self):
        self.disconnected += 1

    async def get_entity(self, chat_id):
        self.scanned.append(chat_id)
        if self.entity_override is not None:
            return self.entity_override
        if chat_id == "@alice":
            return SimpleNamespace(id=1, first_name="Alice")
        return SimpleNamespace(id=chat_id, first_name="Alice")

    async def iter_dialogs(self):
        for dialog in self.dialogs:
            yield dialog

    async def iter_messages(self, chat, *, limit=None, offset_id=0, offset_date=None):
        chat_id = chat if isinstance(chat, int) else chat.id
        self.scanned.append(chat_id)
        emitted = 0
        for msg in self.messages[chat_id]:
            if offset_id and msg.id >= offset_id:
                continue
            if offset_date and msg.date >= offset_date:
                continue
            if limit is not None and emitted >= limit:
                break
            emitted += 1
            yield msg

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((getattr(chat_id, "id", chat_id), text, kwargs))
        if text == "uncertain":
            raise ConnectionError("network error")
        return SimpleNamespace(id=42, date=STAMP)


@pytest.fixture
def setup(tmp_path):
    session = tmp_path / "test.session"
    session.touch(mode=0o600)
    session.chmod(0o600)
    client = FakeClient(str(session), 123, "not-a-real-hash")

    def server(*, allowed=frozenset({1}), send=False):
        return create_server(
            Settings(123, "not-a-real-hash", session, allowed, send), client_factory=lambda *args: client
        )

    return server, client, session


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    if result.isError:
        return result
    if result.structuredContent is not None:
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_registration_and_schemas(setup):
    build, _, _ = setup
    for send, expected in ((False, 3), (True, 4)):
        async with create_connected_server_and_client_session(build(send=send)) as session:
            tools = (await session.list_tools()).tools
            assert len(tools) == expected
            assert {tool.name for tool in tools} == (
                {"telegram_get_conversations", "get_sent_messages", "telegram_get_chat_history"}
                | ({"telegram_send_message"} if send else set())
            )
            assert all(
                tool.annotations and tool.annotations.readOnlyHint
                for tool in tools
                if tool.name != "telegram_send_message"
            )
            if send:
                assert tools[-1].annotations and tools[-1].annotations.readOnlyHint is False
            schemas = {tool.name: tool.inputSchema["properties"] for tool in tools}
            assert {
                "date",
                "start_date",
                "end_date",
                "chat_types",
                "private_allowlist_ids",
                "group_allowlist_ids",
                "group_allowlist_names",
            } <= schemas["telegram_get_conversations"].keys()
            assert {"chat_id", "limit", "before_msg_id"} <= schemas["telegram_get_chat_history"].keys()
            if send:
                assert {"chat_id", "text", "reply_to_message_id"} <= schemas["telegram_send_message"].keys()


@pytest.mark.asyncio
async def test_reads_apply_allowlist_and_date_grouping(setup, capsys):
    build, client, _ = setup
    async with create_connected_server_and_client_session(build()) as session:
        one = await call(session, "telegram_get_conversations", {"date": "2026-01-02"})
        assert one[0]["chat_id"] == 1
        assert one[0]["message_count"] == 1
        grouped = await call(
            session, "telegram_get_conversations", {"start_date": "2026-01-01", "end_date": "2026-01-02"}
        )
        assert [x["date"] for x in grouped] == ["2026-01-01", "2026-01-02"]
        assert [x["chats"][0]["messages"][0]["text"] for x in grouped] == ["yesterday", "hello"]
        sent = await call(session, "get_sent_messages", {"date": "2026-01-02"})
        assert sent[0]["message_id"] == 9
        history = await call(session, "telegram_get_chat_history", {"chat_id": 1, "before_msg_id": 9})
        assert [x["id"] for x in history["messages"]] == [8]
        denied = await call(session, "telegram_get_conversations", {"date": "2026-01-02", "group_allowlist_ids": [2]})
        assert denied.isError
        assert (
            await call(session, "telegram_get_conversations", {"date": "2026-01-02", "group_allowlist_names": ["Team"]})
            == []
        )
        assert (await call(session, "telegram_get_conversations", {"date": "2026-01-02", "chat_types": []})).isError
        assert (await call(session, "telegram_get_chat_history", {"chat_id": 2})).isError
    assert 2 not in client.scanned
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_date_work_budget_and_max_calendar_date(setup):
    build, _, _ = setup
    async with create_connected_server_and_client_session(build()) as session:
        too_large = await call(
            session, "telegram_get_conversations", {"start_date": "2025-11-25", "end_date": "2026-01-02"}
        )
        assert too_large.isError
        last_day = await call(session, "telegram_get_conversations", {"date": "9999-12-31"})
        assert last_day == []


@pytest.mark.asyncio
async def test_history_accepts_username_and_checks_resolved_chat_id(setup):
    build, client, _ = setup
    async with create_connected_server_and_client_session(build()) as session:
        history = await call(session, "telegram_get_chat_history", {"chat_id": "@alice", "limit": 1})
        assert history["chat_id"] == 1
        assert [message["id"] for message in history["messages"]] == [9]
    client.scanned.clear()
    async with create_connected_server_and_client_session(build(allowed=frozenset({2}))) as session:
        denied = await call(session, "telegram_get_chat_history", {"chat_id": "@alice"})
        assert denied.isError
        assert 1 not in client.scanned


@pytest.mark.asyncio
async def test_send_checks_resolved_recipient_not_requested_id(setup):
    build, client, _ = setup
    client.entity_override = SimpleNamespace(id=2, first_name="Different recipient")
    async with create_connected_server_and_client_session(build(send=True)) as session:
        result = await call(session, "telegram_send_message", {"chat_id": 1, "text": "private"})
        assert result.isError
    assert client.sent == []


@pytest.mark.asyncio
async def test_group_name_query_does_not_reveal_excluded_chats(setup):
    build, _, _ = setup
    async with create_connected_server_and_client_session(build()) as session:
        for name in ("Team", "Nonexistent"):
            result = await call(
                session, "telegram_get_conversations", {"date": "2026-01-02", "group_allowlist_names": [name]}
            )
            assert result == []


@pytest.mark.asyncio
async def test_serve_rejects_world_readable_session(setup):
    build, client, path = setup
    path.chmod(0o644)
    async with create_connected_server_and_client_session(build()) as session:
        result = await call(session, "get_sent_messages", {"date": "2026-01-02"})
        assert result.isError
    assert client.connected == 0


@pytest.mark.asyncio
async def test_send_reply_dedup_and_failure(setup):
    build, client, _ = setup
    async with create_connected_server_and_client_session(build(send=True)) as session:
        args = {"chat_id": 1, "text": "hello", "reply_to_message_id": 9}
        assert (await call(session, "telegram_send_message", args))["status"] == "sent"
        assert (await call(session, "telegram_send_message", args))["status"] == "dedup_skipped"
        assert client.sent == [(1, "hello", {"reply_to": 9})]
        assert (await call(session, "telegram_send_message", {**args, "reply_to_message_id": 8}))["status"] == "sent"
        assert (await call(session, "telegram_send_message", {**args, "chat_id": 2})).isError
        uncertain = {"chat_id": 1, "text": "uncertain"}
        assert (await call(session, "telegram_send_message", uncertain))["status"] == "unknown"
        assert (await call(session, "telegram_send_message", uncertain))["status"] == "unknown"
        assert [sent[1] for sent in client.sent].count("uncertain") == 2


@pytest.mark.asyncio
async def test_missing_unauthorized_and_colliding_session(setup):
    from filelock import FileLock

    build, client, path = setup
    client.authorized = False
    async with create_connected_server_and_client_session(build()) as session:
        assert (await call(session, "get_sent_messages", {"date": "2026-01-02"})).isError
    assert client.disconnected == 1
    client.authorized = True
    with FileLock(str(path) + ".lock"):
        async with create_connected_server_and_client_session(build()) as session:
            assert (await call(session, "get_sent_messages", {"date": "2026-01-02"})).isError
    path.unlink()
    async with create_connected_server_and_client_session(build()) as session:
        assert (await call(session, "get_sent_messages", {"date": "2026-01-02"})).isError
