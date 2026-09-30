"""Interactive, local-only Telegram session login."""

import getpass

import qrcode
from filelock import FileLock
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from telegram_account_mcp.config import Settings


def _render_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def login(
    settings: Settings,
    *,
    method: str = "qr",
    client_factory=TelegramClient,
    input_fn=input,
    password_fn=getpass.getpass,
) -> None:
    """Create a private session using QR login or an explicit phone fallback."""
    if method not in {"qr", "phone"}:
        raise ValueError("Login method must be 'qr' or 'phone'")

    session_path = settings.session_path
    new_directory = not session_path.parent.exists()
    session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if new_directory:
        session_path.parent.chmod(0o700)
    lock = FileLock(str(session_path) + ".lock", timeout=0, mode=0o600)
    with lock:
        session_path.touch(mode=0o600, exist_ok=True)
        session_path.chmod(0o600)
        client = None
        try:
            client = client_factory(str(session_path), settings.api_id, settings.api_hash)
            await client.connect()
            if session_path.exists():
                session_path.chmod(0o600)
            if not await client.is_user_authorized():
                if method == "qr":
                    print("Scan with Telegram: Settings > Devices > Link Desktop Device")
                    qr = await client.qr_login()
                    while True:
                        _render_qr(qr.url)
                        try:
                            await qr.wait()
                            break
                        except TimeoutError:
                            await qr.recreate()
                            print("QR expired; scan the new code.")
                        except SessionPasswordNeededError:
                            await client.sign_in(password=password_fn("Telegram 2FA password: "))
                            break
                else:
                    phone = input_fn("Telegram phone number: ")
                    await client.send_code_request(phone)
                    code = input_fn("Telegram login code: ")
                    try:
                        await client.sign_in(phone=phone, code=code)
                    except SessionPasswordNeededError:
                        await client.sign_in(password=password_fn("Telegram 2FA password: "))

                if not await client.is_user_authorized():
                    raise RuntimeError("Telegram login did not authorize the session")
            print("Telegram session authorized.")
        finally:
            try:
                if client is not None:
                    await client.disconnect()
            finally:
                if session_path.exists():
                    session_path.chmod(0o600)
