"""Config and real stdio MCP launch without credentials or account access."""

import os
import shutil
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from telegram_account_mcp.config import load_settings


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_API_HASH", "fake-hash")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "account.session"))
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ENABLE_SEND", raising=False)
    return tmp_path


def test_config_fails_loud_on_missing_or_malformed_settings(fake_env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID")
    with pytest.raises(ValueError, match="TELEGRAM_API_ID"):
        load_settings()
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        load_settings()
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "1, -1005")
    monkeypatch.setenv("TELEGRAM_ENABLE_SEND", "1")
    settings = load_settings()
    assert settings.allowed_chat_ids == frozenset({1, -1005})
    assert settings.enable_send is True
    monkeypatch.setenv("TELEGRAM_ENABLE_SEND", "sure")
    with pytest.raises(ValueError, match="TELEGRAM_ENABLE_SEND"):
        load_settings()


@pytest.mark.asyncio
@pytest.mark.parametrize("send", ["0", "1"])
async def test_real_stdio_host_command_exposes_expected_tools_without_login(fake_env, send):
    project = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv unavailable: project requires uv to run MCP host command")
    env = {
        **os.environ,
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "fake-hash",
        "TELEGRAM_SESSION_PATH": str(fake_env / "nonexistent.session"),
        "TELEGRAM_ENABLE_SEND": send,
    }
    # The real documented command starts a fresh server; only list_tools is called.
    params = StdioServerParameters(
        command=uv, args=["--directory", str(project), "run", "--no-sync", "telegram-account-mcp", "serve"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
    expected = {"telegram_get_chat_history", "telegram_get_conversations", "get_sent_messages"}
    assert names == expected | ({"telegram_send_message"} if send == "1" else set())
