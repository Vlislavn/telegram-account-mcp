# Telegram account MCP

Local Telegram **user-account** MCP for Codex CLI and Claude Code. QR login is the default; no bot or web server.

**QR replaces phone/code login—not API credentials.** This user-account MCP **cannot work without** `api_id` and `api_hash`; a bot token is not a substitute for access to your personal chats. Get the credentials once ([Telegram's instructions](https://core.telegram.org/api/obtaining_api_id)):

1. Sign in at [my.telegram.org](https://my.telegram.org/) with the phone number of your Telegram account and the code Telegram sends you.
2. Open **API development tools** and create an application (fill in the required title, short name and other fields).
3. Copy its numeric **api_id** and **api_hash** into your private `.env` as `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. Never paste them into an agent chat.

## 1. Sign in with QR

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/Vlislavn/telegram-account-mcp.git
cd telegram-account-mcp
uv sync --locked --no-dev
cp .env.example .env
chmod 600 .env
```

After filling in `.env`, run `uv run --no-sync telegram-account-mcp login`.

On your phone: **Telegram → Settings → Devices → Link Desktop Device → scan the terminal QR**. Expired QR codes refresh automatically; enter your 2FA password if asked. The session is saved privately outside the repo at `~/.local/share/telegram-account-mcp/session.session`. If QR is unavailable, use `uv run --no-sync telegram-account-mcp login --phone` instead.

## 2. Connect one agent

Use your **absolute checkout path** and choose one command:

```bash
codex mcp add telegram -- uv --directory "/absolute/path/to/telegram-account-mcp" run --no-sync telegram-account-mcp serve
# or, from the Claude Code project where you want access:
claude mcp add --scope local telegram -- uv --directory "/absolute/path/to/telegram-account-mcp" run --no-sync telegram-account-mcp serve
```

Restart the agent; check `codex mcp list` or `claude mcp list`. No extra agent instructions are needed.

**Tools:** per-chat text history (by ID or @username), conversations by date (up to 31 days), outgoing messages by date. Sending text/replies is **off by default**. To expose it, set `TELEGRAM_ENABLE_SEND=1` in `.env` and restart the agent; configure its per-call approval before sending. An uncertain send (`status=unknown`) must be checked in Telegram before retrying. Optional `TELEGRAM_ALLOWED_CHAT_IDS` restricts every tool to numeric chat IDs; unset means all accessible chats.

**Privacy:** never publish `.env` or `.session`. MCP message text can reach the agent's model provider. Two agents should not use one session simultaneously. QR/phone login has offline tests, but a real login still requires the owner to scan/confirm; it has not been verified with a live account.

Run offline tests: `uv sync --locked && uv run pytest -q`. [Changes](CHANGELOG.md) · [MIT license](LICENSE).
