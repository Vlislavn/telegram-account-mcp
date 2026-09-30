from pathlib import Path

import pytest
from filelock import FileLock, Timeout
from telethon.errors import SessionPasswordNeededError

from telegram_account_mcp import auth
from telegram_account_mcp.config import Settings


class FakeQR:
    def __init__(self, *, timeouts=0, password=False):
        self.url = "tg://login?token=secret"
        self.timeouts = timeouts
        self.password = password
        self.recreated = 0
        self.client = None

    async def wait(self):
        if self.timeouts:
            self.timeouts -= 1
            raise TimeoutError
        if self.password:
            raise SessionPasswordNeededError(request=None)
        self.client.authorized = True

    async def recreate(self):
        self.recreated += 1
        self.url = "tg://login?token=next-secret"


class FakeClient:
    def __init__(self, path, api_id, api_hash, *, authorized=False, qr=None, fail=None, phone_password=False):
        self.path = Path(path)
        self.authorized = authorized
        self.qr = qr
        self.fail = fail
        self.phone_password = phone_password
        self.disconnected = False
        self.calls = []
        if qr is not None:
            qr.client = self

    async def connect(self):
        self.calls.append("connect")
        self.path.write_text("fake session")
        self.path.chmod(0o644)
        if self.fail:
            raise RuntimeError("connection failed")

    async def disconnect(self):
        self.disconnected = True
        self.calls.append("disconnect")

    async def is_user_authorized(self):
        return self.authorized

    async def qr_login(self):
        self.calls.append("qr_login")
        return self.qr

    async def send_code_request(self, phone):
        self.calls.append(("send_code_request", phone))

    async def sign_in(self, *, phone=None, code=None, password=None):
        if phone and self.phone_password:
            raise SessionPasswordNeededError(request=None)
        self.calls.append(("sign_in", phone, code, password))
        self.authorized = True


@pytest.fixture
def settings(tmp_path):
    return Settings(123, "private-api-hash", tmp_path / "sessions" / "account.session", None, False)


def test_terminal_qr_renderer_emits_blocks_without_raw_token(capsys):
    auth._render_qr("tg://login?token=fixture-not-real")
    output = capsys.readouterr().out
    assert len(output.splitlines()) > 10
    assert "fixture-not-real" not in output
    assert "█" in output


@pytest.mark.asyncio
async def test_already_authorized(settings, capsys):
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, authorized=True)
    await auth.login(settings, client_factory=lambda *args: client)
    assert client.calls == ["connect", "disconnect"]
    assert client.disconnected
    assert settings.session_path.parent.stat().st_mode & 0o777 == 0o700
    assert settings.session_path.stat().st_mode & 0o777 == 0o600
    assert "private-api-hash" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_qr_timeout_refresh(settings, monkeypatch, capsys):
    qr = FakeQR(timeouts=1)
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, qr=qr)
    urls = []
    monkeypatch.setattr(auth, "_render_qr", urls.append)
    await auth.login(settings, client_factory=lambda *args: client)
    assert qr.recreated == 1
    assert urls == ["tg://login?token=secret", "tg://login?token=next-secret"]
    assert client.disconnected
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "private-api-hash" not in output


@pytest.mark.asyncio
async def test_qr_password(settings, monkeypatch):
    qr = FakeQR(password=True)
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, qr=qr)
    monkeypatch.setattr(auth, "_render_qr", lambda url: None)
    await auth.login(settings, client_factory=lambda *args: client, password_fn=lambda prompt: "2fa-secret")
    assert ("sign_in", None, None, "2fa-secret") in client.calls
    assert client.disconnected


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_password", [False, True])
async def test_phone(settings, capsys, needs_password):
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, phone_password=needs_password)
    entries = iter(["+123456789", "12345"])
    await auth.login(
        settings,
        method="phone",
        client_factory=lambda *args: client,
        input_fn=lambda prompt: next(entries),
        password_fn=lambda prompt: "2fa-secret",
    )
    assert ("send_code_request", "+123456789") in client.calls
    assert (
        ("sign_in", None, None, "2fa-secret") in client.calls
        if needs_password
        else ("sign_in", "+123456789", "12345", None) in client.calls
    )
    assert client.disconnected
    assert "+123456789" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_disconnects_and_protects_session(settings):
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, fail=True)
    with pytest.raises(RuntimeError, match="connection failed"):
        await auth.login(settings, client_factory=lambda *args: client)
    assert client.disconnected
    assert settings.session_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_login_does_not_change_permissions_of_existing_custom_parent(settings):
    settings.session_path.parent.mkdir(mode=0o755)
    settings.session_path.parent.chmod(0o755)
    client = FakeClient(settings.session_path, settings.api_id, settings.api_hash, authorized=True)
    await auth.login(settings, client_factory=lambda *args: client)
    assert settings.session_path.parent.stat().st_mode & 0o777 == 0o755
    assert settings.session_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_lock_prevents_concurrent_login(settings):
    settings.session_path.parent.mkdir()
    lock = FileLock(str(settings.session_path) + ".lock")
    with lock:
        with pytest.raises(Timeout):
            await auth.login(settings, client_factory=lambda *args: pytest.fail("must not connect"))


@pytest.mark.asyncio
async def test_invalid_method_does_not_connect(settings):
    with pytest.raises(ValueError, match="Login method"):
        await auth.login(settings, method="unknown", client_factory=lambda *args: pytest.fail("must not connect"))
