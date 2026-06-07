# Qubit

Qubit is a market intelligence platform that combines analytics, risk management, and execution to help traders make disciplined decisions across global markets.

## Run & Operate

- `python3 bot/main.py` — run the Qubit Telegram bot
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- Required env: `TELEGRAM_BOT_TOKEN` — Telegram bot token (set via Replit Secrets)

## Stack

- Python 3.11, python-telegram-bot 21.6, SQLite (via sqlite3)
- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- Bot DB: SQLite at `bot/qai.db` — trades, paper_trades, settings tables

## Where things live

- `bot/main.py` — all Telegram handlers, menus, conversation flows
- `bot/database.py` — SQLite schema, all queries (trades, paper trades, market filters, settings)
- `bot/paper_engine.py` — paper trade lifecycle: open, close, PnL calculation
- `bot/risk.py` — Qubit Risk (QR): risk limits, status display
- `bot/validator.py` — Qubit Analytics (QA): signal validation rules
- `bot/qai.db` — SQLite database (auto-created on first run)

## Architecture

```
Qubit Markets (QM)     → Market Data Layer      (market filters in database.py)
Qubit Analytics (QA)   → Analysis & Signal Engine (validator.py)
Qubit Risk (QR)        → Risk Management Layer  (risk.py)
Qubit Executor (QX)    → Execution Layer        (paper_engine.py)
Telegram Bot           → User Interface         (main.py)
```

## Signal Flow

1. Market filter check (QM) — blocks if trend flat / high vol / news risk active
2. Qubit Analytics (QA) — validates confidence ≥65%, SL/TP structure
3. Qubit Risk (QR) — checks daily loss limit, open trade cap, consecutive loss pause
4. Paper trade opened on approval (QX)

## Risk Controls

- 1% risk per trade (dynamic, based on current balance)
- Max 3 open trades per day
- Max 5% daily loss limit
- Auto-pause after 3 consecutive losses
- Balance stored in SQLite settings table

## Commands

/start /help /approved /rejected /stats /risk /performance /trades /open_trades /daily_report /market_status /setbalance

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Run `python3 bot/main.py` from workspace root — sys.path is set inside the file
- PTBUserWarning suppressed via warnings.filterwarnings (per_message=False on ConversationHandlers)
- Market filter toggles persist in SQLite settings table; they survive restarts
- Balance is stored in settings table key `balance`; defaults to $10,000
- To swap the Telegram bot token: update the `TELEGRAM_BOT_TOKEN` secret in Replit Secrets

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
