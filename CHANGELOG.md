# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Local stdio Telegram MCP with text history, date-grouped reads, opt-in sends, chat allowlists, and QR/phone login; no conversation cache.
- Restrict reads/sends by chat, recheck resolved recipients, require private sessions, and cap date queries to 31 days.
- Verify terminal QR rendering alongside fake-client login and real stdio MCP protocol tests.

### Changed
- Make QR the clear onboarding path and halve the setup guide; clarify that Telegram API ID/hash remain mandatory.
