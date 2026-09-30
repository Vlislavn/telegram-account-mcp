# Telegram account MCP

Local **user-account** Telegram tools for Codex CLI and Claude Code. One stdio process, no bot token, web server, message cache or LLM preprocessing. Reading is the default; sending is opt-in.

```text
Codex / Claude Code → local MCP (stdio) → Telethon session → your Telegram account
```

## Set up once

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Codex CLI or Claude Code, and your own Telegram API credentials from [my.telegram.org/apps](https://my.telegram.org/apps). Do not use somebody else's credentials or session file.

```bash
git clone https://github.com/Vlislavn/telegram-account-mcp.git
cd telegram-account-mcp
uv sync --locked --no-dev
cp .env.example .env
chmod 600 .env
```

Put `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from **your** Telegram API app into `.env` (not into the agent prompt or `mcp add` arguments). Then authorize on this machine:

```bash
uv run --no-sync telegram-account-mcp login
```

The terminal shows one QR code at a time. On your phone: **Telegram → Settings → Devices → Link Desktop Device → scan**. Expired codes refresh; if Telegram requests 2FA, enter its password in the terminal. If QR is unavailable, use `uv run --no-sync telegram-account-mcp login --phone` and enter your number and the Telegram verification code interactively. Do not paste either credential into a chat. Successful login prints `Telegram session authorized.`; the session stays outside the checkout at `~/.local/share/telegram-account-mcp/session.session` (owner-only). For an override via `TELEGRAM_SESSION_PATH`, choose a private directory yourself; the program will not change permissions on an existing directory.

## Connect an agent

Use the **absolute checkout path**. Register only in clients you actually use; these are two alternatives:

```bash
codex mcp add telegram -- uv --directory "/absolute/path/to/telegram-account-mcp" run --no-sync telegram-account-mcp serve
# OR (run from the Claude Code project where you need Telegram):
claude mcp add --scope local telegram -- uv --directory "/absolute/path/to/telegram-account-mcp" run --no-sync telegram-account-mcp serve
```

Check `codex mcp list` or `claude mcp list`, start a **new** agent session, and ask it to use the `telegram` MCP to read a chat's recent text history. No extra instructions/skill are required: MCP advertises the tool names and schemas. The host starts/stops the stdio server; do not run `serve` manually in a regular terminal and expect a chat interface. One session file permits **one connected MCP call at a time**; two agents using it simultaneously may receive `Telegram session in use`. Use the agents sequentially, or authorize separate sessions with `TELEGRAM_SESSION_PATH` if concurrent clients are needed.

### Available tools

| Tool | Operation |
| --- | --- |
| `telegram_get_chat_history(chat_id, limit=50, before_msg_id=None)` | Newest-first text/history, page by message ID. |
| `telegram_get_conversations(date OR start_date/end_date, filters...)` | Incoming and outgoing text grouped by chat/day; optional private/group ID, group name and chat-type filters. |
| `get_sent_messages(date)` | Outgoing text across chats on one ISO date. |
| `telegram_send_message(chat_id, text, reply_to_message_id=None)` | **Off by default.** Send text/reply as your account. |

No media download/upload, voice transcription, live watch, global search or hidden AI summaries. Date-wide reads can be slow or return a large amount of personal text: one call covers at most 31 days; split longer ranges. Prefer one chat and small limits. An optional `TELEGRAM_ALLOWED_CHAT_IDS` in `.env` limits **all four** tools to comma-separated numeric chat IDs. Unset means the session can read every accessible chat. To discover an ID, run a small date query first, then set the allowlist and restart the agent; do not treat a prompt asking the model to avoid a chat as access control.

If sending is needed, set `TELEGRAM_ENABLE_SEND=1` in `.env` and restart the agent. That registers the send tool; it does **not** add a server-side approval dialog. Set your agent's per-call permission gate and check the recipient/text before approving. A response of `status=unknown` means delivery is **uncertain**: inspect the chat manually before retrying. Identical confirmed sends to the same recipient/reply are suppressed for 60 seconds within one server process, not across restarts.

## Privacy and limits

- This is a **user account**, not a Telegram bot. `.session` grants account access: never commit or share it. `.env`, sessions, caches and credentials are excluded from Git by a publication allowlist.
- Message text returned through MCP enters the agent's context and may go to its model provider. Read-only tools do not mean local-only analysis.
- Session lock prevents this server from racing another instance using the same file; use one session per simultaneously running agent. Telegram rate limits still apply. Tested on macOS with Linux CI; Windows is not yet validated.
- No live login can be proven by offline tests. The QR and phone flows have fake-client tests; the final real-account check requires the account owner to scan/confirm on their own device. This repository never includes any account session or test chat.

## Development and validation

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests cover QR expiry/2FA/phone, session protection, tool registration, local MCP calls, date grouping, chat allowlist and opt-in sends without a real Telegram account. See [CHANGELOG.md](CHANGELOG.md) for release changes. Source is licensed under [MIT](LICENSE).
