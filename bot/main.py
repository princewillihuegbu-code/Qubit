import os
import json
import logging
import warnings
from datetime import date
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.warnings import PTBUserWarning
warnings.filterwarnings("ignore", category=PTBUserWarning)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data.json"

CHOOSING_DIRECTION, ENTERING_TICKER, CHOOSING_DECISION = range(3)


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


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("📡 Log Signal", callback_data="log_signal"),
        ],
        [
            InlineKeyboardButton("📋 Today's Signals", callback_data="signals_list"),
            InlineKeyboardButton("📈 Summary", callback_data="summary"),
        ],
        [
            InlineKeyboardButton("🔄 Reset", callback_data="reset"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to Q AI.\n"
        "Quantum Execution Intelligence System.\n"
        "Status: Active"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Q AI — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard()
    )


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = load_data()
    text = (
        "Q AI Status\n"
        "Mode: Signal Monitoring\n"
        f"Signals Today: {len(data['signals'])}\n"
        f"Approved Trades: {data['approved']}\n"
        f"Rejected Trades: {data['rejected']}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_signals_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = load_data()
    signals = data["signals"]
    if not signals:
        text = "No signals logged today."
    else:
        lines = ["Today's Signals:\n"]
        for i, s in enumerate(signals, 1):
            lines.append(f"{i}. {s['direction']} {s['ticker']} — {s['decision'].capitalize()}")
        text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Reset", callback_data="reset_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu"),
        ]
    ])
    await query.edit_message_text(
        "⚠️ Reset all signal data for today?\nThis cannot be undone.",
        reply_markup=keyboard
    )


async def do_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = {"date": str(date.today()), "signals": [], "approved": 0, "rejected": 0}
    save_data(data)
    await query.edit_message_text(
        "✅ Signal data reset.\nAll counts cleared for today.",
        reply_markup=back_keyboard()
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "Q AI — Help\n\n"
        "📊 Status — View today's signal counts\n"
        "📡 Log Signal — Record a new trade signal step by step\n"
        "📋 Today's Signals — See all signals logged today\n"
        "🔄 Reset — Clear today's signal data\n\n"
        "Use /start to return to the main menu at any time."
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = load_data()
    signals = data["signals"]
    total = len(signals)

    if total == 0:
        await query.edit_message_text(
            "📈 End-of-Day Summary\n\nNo signals logged today.",
            reply_markup=back_keyboard()
        )
        return

    approved = data["approved"]
    rejected = data["rejected"]
    win_rate = (approved / total) * 100

    ticker_counts: dict[str, int] = {}
    buy_count = 0
    sell_count = 0
    for s in signals:
        ticker_counts[s["ticker"]] = ticker_counts.get(s["ticker"], 0) + 1
        if s["direction"] == "BUY":
            buy_count += 1
        else:
            sell_count += 1

    ranked = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    top_tickers = "\n".join(
        f"  {i+1}. {ticker} — {count} signal{'s' if count > 1 else ''}"
        for i, (ticker, count) in enumerate(ranked[:5])
    )

    bar_filled = round(win_rate / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    text = (
        f"📈 End-of-Day Summary — {data['date']}\n"
        f"{'─' * 30}\n\n"
        f"Total Signals:   {total}\n"
        f"Approved:        {approved}  ✅\n"
        f"Rejected:        {rejected}  ❌\n\n"
        f"Win Rate:  {win_rate:.1f}%\n"
        f"[{bar}]\n\n"
        f"Direction Split:\n"
        f"  📈 BUY:  {buy_count}\n"
        f"  📉 SELL: {sell_count}\n\n"
        f"Top Tickers:\n{top_tickers}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def signal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 BUY", callback_data="dir_BUY"),
            InlineKeyboardButton("📉 SELL", callback_data="dir_SELL"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_signal")],
    ])
    await query.edit_message_text(
        "Step 1 of 3 — Choose direction:",
        reply_markup=keyboard
    )
    return CHOOSING_DIRECTION


async def signal_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    direction = query.data.split("_")[1]
    context.user_data["signal_direction"] = direction
    await query.edit_message_text(
        f"Step 2 of 3 — Direction: {direction}\n\nType the ticker symbol (e.g. AAPL, TSLA, BTC):"
    )
    return ENTERING_TICKER


async def signal_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ticker = update.message.text.strip().upper()
    context.user_data["signal_ticker"] = ticker
    direction = context.user_data["signal_direction"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data="dec_approve"),
            InlineKeyboardButton("❌ Reject", callback_data="dec_reject"),
        ],
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_signal_msg")],
    ])
    await update.message.reply_text(
        f"Step 3 of 3 — {direction} {ticker}\n\nApprove or reject this trade?",
        reply_markup=keyboard
    )
    return CHOOSING_DECISION


async def signal_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    decision = query.data.split("_")[1]
    direction = context.user_data.get("signal_direction", "?")
    ticker = context.user_data.get("signal_ticker", "?")

    data = load_data()
    data["signals"].append({
        "direction": direction,
        "ticker": ticker,
        "decision": decision,
        "time": str(date.today())
    })
    if decision == "approve":
        data["approved"] += 1
        label = "Approved ✅"
    else:
        data["rejected"] += 1
        label = "Rejected ❌"
    save_data(data)

    context.user_data.clear()
    text = (
        f"Signal Logged\n"
        f"Direction: {direction}\n"
        f"Ticker: {ticker}\n"
        f"Decision: {label}\n\n"
        f"Signals Today: {len(data['signals'])} | "
        f"Approved: {data['approved']} | "
        f"Rejected: {data['rejected']}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())
    return ConversationHandler.END


async def cancel_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\nQ AI — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def cancel_signal_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\nQ AI — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    app = Application.builder().token(token).build()

    signal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(signal_start, pattern="^log_signal$")],
        states={
            CHOOSING_DIRECTION: [
                CallbackQueryHandler(signal_direction, pattern="^dir_"),
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
            ],
            ENTERING_TICKER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_ticker),
            ],
            CHOOSING_DECISION: [
                CallbackQueryHandler(signal_decision, pattern="^dec_"),
                CallbackQueryHandler(cancel_signal_msg, pattern="^cancel_signal_msg$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(signal_conv)
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_status, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(show_signals_list, pattern="^signals_list$"))
    app.add_handler(CallbackQueryHandler(show_reset_confirm, pattern="^reset$"))
    app.add_handler(CallbackQueryHandler(do_reset, pattern="^reset_confirm$"))
    app.add_handler(CallbackQueryHandler(show_help, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(show_summary, pattern="^summary$"))

    logger.info("Q AI bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
