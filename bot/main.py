import os
import json
import logging
from datetime import date
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data.json"


def load_data() -> dict:
    today = str(date.today())
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        if data.get("date") != today:
            data = {"date": today, "signals": [], "approved": 0, "rejected": 0}
            save_data(data)
    else:
        data = {"date": today, "signals": [], "approved": 0, "rejected": 0}
        save_data(data)
    return data


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to Q AI.\n"
        "Quantum Execution Intelligence System.\n"
        "Status: Active"
    )
    await update.message.reply_text(text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    signals_today = len(data["signals"])
    approved = data["approved"]
    rejected = data["rejected"]
    text = (
        "Q AI Status\n"
        "Mode: Signal Monitoring\n"
        f"Signals Today: {signals_today}\n"
        f"Approved Trades: {approved}\n"
        f"Rejected Trades: {rejected}"
    )
    await update.message.reply_text(text)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = (
        "Usage: /signal <DIRECTION> <TICKER> <approve|reject>\n"
        "Example: /signal BUY AAPL approve\n"
        "Example: /signal SELL TSLA reject"
    )

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(usage)
        return

    direction = args[0].upper()
    ticker = args[1].upper()
    decision = args[2].lower()

    if direction not in ("BUY", "SELL"):
        await update.message.reply_text(f"Invalid direction '{args[0]}'. Use BUY or SELL.\n\n{usage}")
        return

    if decision not in ("approve", "reject"):
        await update.message.reply_text(f"Invalid decision '{args[2]}'. Use approve or reject.\n\n{usage}")
        return

    data = load_data()

    entry = {
        "direction": direction,
        "ticker": ticker,
        "decision": decision,
        "time": str(date.today())
    }
    data["signals"].append(entry)

    if decision == "approve":
        data["approved"] += 1
        status_label = "Approved"
    else:
        data["rejected"] += 1
        status_label = "Rejected"

    save_data(data)

    text = (
        f"Signal Logged\n"
        f"Direction: {direction}\n"
        f"Ticker: {ticker}\n"
        f"Decision: {status_label}\n\n"
        f"Signals Today: {len(data['signals'])} | "
        f"Approved: {data['approved']} | "
        f"Rejected: {data['rejected']}"
    )
    await update.message.reply_text(text)


async def signals_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    signals = data["signals"]
    if not signals:
        await update.message.reply_text("No signals logged today.")
        return

    lines = ["Today's Signals:\n"]
    for i, s in enumerate(signals, 1):
        lines.append(f"{i}. {s['direction']} {s['ticker']} — {s['decision'].capitalize()}")

    await update.message.reply_text("\n".join(lines))


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = str(date.today())
    data = {"date": today, "signals": [], "approved": 0, "rejected": 0}
    save_data(data)
    await update.message.reply_text("All signal data for today has been reset.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Q AI — Available Commands\n\n"
        "/start — Welcome message and system status\n"
        "/status — View current signal monitoring stats\n"
        "/signal <DIR> <TICKER> <approve|reject> — Log a trade signal\n"
        "/signals — List all signals logged today\n"
        "/reset — Clear today's signal data\n"
        "/help — Show this list of commands\n\n"
        "Example:\n"
        "/signal BUY AAPL approve\n"
        "/signal SELL TSLA reject"
    )
    await update.message.reply_text(text)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("signals", signals_list))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("help", help_command))

    logger.info("Q AI bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
