import os
import sys
import logging
import warnings

sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
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

from database import (
    init_db,
    insert_trade,
    get_trades_by_status,
    get_approved_count_today,
    get_consecutive_losses,
    get_stats_today,
    get_all_time_stats,
)
from validator import Signal, validate_signal
from risk import check_risk, calculate_rr, risk_status_text, RISK_PER_TRADE

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

(
    SIGNAL_SYMBOL,
    SIGNAL_DIRECTION,
    SIGNAL_ENTRY,
    SIGNAL_SL,
    SIGNAL_TP,
    SIGNAL_CONFIDENCE,
) = range(6)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 Log Signal", callback_data="log_signal"),
            InlineKeyboardButton("⚠️ Risk", callback_data="risk"),
        ],
        [
            InlineKeyboardButton("✅ Approved", callback_data="approved"),
            InlineKeyboardButton("❌ Rejected", callback_data="rejected"),
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
            InlineKeyboardButton("📈 Summary", callback_data="summary"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Day", callback_data="reset"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Cancel Signal", callback_data="cancel_signal")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to Q AI.\nQuantum Execution Intelligence System.\nVersion 2.0 — Active",
        reply_markup=main_menu_keyboard(),
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Q AI v2.0 — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard(),
    )


async def show_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    approved_today = get_approved_count_today()
    consecutive = get_consecutive_losses()
    text = risk_status_text(approved_today, consecutive)
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    trades = get_trades_by_status("approved")
    if not trades:
        text = "✅ Approved Trades\n\nNo approved trades today."
    else:
        lines = [f"✅ Approved Trades Today — {len(trades)}\n"]
        for t in trades:
            lines.append(
                f"#{t['id']} {t['direction']} {t['symbol']}\n"
                f"   Entry: {t['entry']} | SL: {t['stop_loss']} | TP: {t['take_profit']}\n"
                f"   Confidence: {t['confidence']:.0f}% | R:R {t['rr_ratio']} | Risk: ${t['risk_amount']:.0f}\n"
            )
        text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_rejected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    trades = get_trades_by_status("rejected")
    if not trades:
        text = "❌ Rejected Signals\n\nNo rejected signals today."
    else:
        lines = [f"❌ Rejected Signals Today — {len(trades)}\n"]
        for t in trades:
            lines.append(
                f"#{t['id']} {t['direction']} {t['symbol']}\n"
                f"   Confidence: {t['confidence']:.0f}%\n"
                f"   Reason: {t['reason']}\n"
            )
        text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    today = get_stats_today()
    alltime = get_all_time_stats()

    def win_rate(d: dict) -> str:
        if d["total"] == 0:
            return "N/A"
        return f"{(d['approved'] / d['total']) * 100:.1f}%"

    text = (
        "📊 Q AI — Statistics\n"
        f"{'─' * 28}\n\n"
        f"Today ({date.today()})\n"
        f"  Total Signals:  {today['total']}\n"
        f"  Approved:       {today['approved']}  ✅\n"
        f"  Rejected:       {today['rejected']}  ❌\n"
        f"  Approval Rate:  {win_rate(today)}\n\n"
        f"All Time\n"
        f"  Total Signals:  {alltime['total']}\n"
        f"  Approved:       {alltime['approved']}  ✅\n"
        f"  Rejected:       {alltime['rejected']}  ❌\n"
        f"  Approval Rate:  {win_rate(alltime)}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    today = get_stats_today()
    total = today["total"]

    if total == 0:
        await query.edit_message_text(
            "📈 End-of-Day Summary\n\nNo signals logged today.",
            reply_markup=back_keyboard(),
        )
        return

    approved = today["approved"]
    rejected = today["rejected"]
    win_rate = (approved / total) * 100
    approved_today = get_approved_count_today()
    committed = approved_today * RISK_PER_TRADE

    bar_filled = round(win_rate / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    trades = get_trades_by_status("approved")
    ticker_counts: dict[str, int] = {}
    buy_count = 0
    sell_count = 0
    for t in trades:
        ticker_counts[t["symbol"]] = ticker_counts.get(t["symbol"], 0) + 1
        if t["direction"] == "BUY":
            buy_count += 1
        else:
            sell_count += 1

    ranked = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    top_tickers = "\n".join(
        f"  {i+1}. {sym} — {cnt} signal{'s' if cnt > 1 else ''}"
        for i, (sym, cnt) in enumerate(ranked[:5])
    ) or "  None"

    text = (
        f"📈 End-of-Day Summary — {date.today()}\n"
        f"{'─' * 30}\n\n"
        f"Total Signals:    {total}\n"
        f"Approved:         {approved}  ✅\n"
        f"Rejected:         {rejected}  ❌\n\n"
        f"Approval Rate:  {win_rate:.1f}%\n"
        f"[{bar}]\n\n"
        f"Capital Committed: ${committed:.0f}\n\n"
        f"Direction Split (Approved):\n"
        f"  📈 BUY:  {buy_count}\n"
        f"  📉 SELL: {sell_count}\n\n"
        f"Top Symbols:\n{top_tickers}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def show_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="reset_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu"),
        ]
    ])
    await query.edit_message_text(
        "⚠️ Reset today's session?\n\nThis clears the daily risk counters "
        "and consecutive loss tracker.\nSQLite trade history is preserved.",
        reply_markup=keyboard,
    )


async def do_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ Day reset complete.\nRisk counters cleared. Trade history preserved.",
        reply_markup=back_keyboard(),
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "Q AI v2.0 — Help\n\n"
        "📡 Log Signal — Submit a new trade signal (6-field validation)\n"
        "⚠️ Risk — View live risk engine status\n"
        "✅ Approved — Today's approved trades\n"
        "❌ Rejected — Today's rejected signals with reasons\n"
        "📊 Stats — Today and all-time approval stats\n"
        "📈 Summary — End-of-day report\n"
        "🔄 Reset Day — Clear daily counters\n\n"
        "Signal Validation Rules:\n"
        "  • Confidence must be ≥ 65%\n"
        "  • SL below Entry (BUY) / above Entry (SELL)\n"
        "  • TP above Entry (BUY) / below Entry (SELL)\n\n"
        "Risk Engine Limits:\n"
        "  • $100 risk per trade (1%)\n"
        "  • Max 3 open trades/day\n"
        "  • Max 5% daily loss ($500)\n"
        "  • Pause after 3 consecutive losses\n\n"
        "Mode: Paper Trading Only"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def signal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "📡 Q Signal Logger — Step 1 of 6\n\n"
        "Enter the symbol (e.g. AAPL, TSLA, BTCUSD):",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_SYMBOL


async def signal_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 BUY", callback_data="dir_BUY"),
            InlineKeyboardButton("📉 SELL", callback_data="dir_SELL"),
        ],
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_signal_msg")],
    ])
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 2 of 6\n\n"
        f"Symbol: {context.user_data['symbol']}\n\n"
        f"Choose trade direction:",
        reply_markup=keyboard,
    )
    return SIGNAL_DIRECTION


async def signal_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["direction"] = query.data.split("_")[1]
    await query.edit_message_text(
        f"📡 Q Signal Logger — Step 3 of 6\n\n"
        f"Symbol: {context.user_data['symbol']} | Direction: {context.user_data['direction']}\n\n"
        f"Enter Entry Price:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_ENTRY


async def signal_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["entry"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Invalid price. Enter a numeric value (e.g. 150.25):",
            reply_markup=cancel_keyboard(),
        )
        return SIGNAL_ENTRY
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 4 of 6\n\n"
        f"Symbol: {context.user_data['symbol']} | Direction: {context.user_data['direction']}\n"
        f"Entry: {context.user_data['entry']}\n\n"
        f"Enter Stop Loss:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_SL


async def signal_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["stop_loss"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Invalid price. Enter a numeric value:",
            reply_markup=cancel_keyboard(),
        )
        return SIGNAL_SL
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 5 of 6\n\n"
        f"Symbol: {context.user_data['symbol']} | Direction: {context.user_data['direction']}\n"
        f"Entry: {context.user_data['entry']} | SL: {context.user_data['stop_loss']}\n\n"
        f"Enter Take Profit:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_TP


async def signal_tp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["take_profit"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Invalid price. Enter a numeric value:",
            reply_markup=cancel_keyboard(),
        )
        return SIGNAL_TP
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 6 of 6\n\n"
        f"Symbol: {context.user_data['symbol']} | Direction: {context.user_data['direction']}\n"
        f"Entry: {context.user_data['entry']} | SL: {context.user_data['stop_loss']} | TP: {context.user_data['take_profit']}\n\n"
        f"Enter Confidence Score (0–100):",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_CONFIDENCE


async def signal_confidence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        confidence = float(update.message.text.strip())
        if not (0 <= confidence <= 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Invalid score. Enter a number between 0 and 100:",
            reply_markup=cancel_keyboard(),
        )
        return SIGNAL_CONFIDENCE

    context.user_data["confidence"] = confidence
    d = context.user_data

    signal = Signal(
        symbol=d["symbol"],
        direction=d["direction"],
        entry=d["entry"],
        stop_loss=d["stop_loss"],
        take_profit=d["take_profit"],
        confidence=d["confidence"],
    )

    validation = validate_signal(signal)

    if not validation.valid:
        insert_trade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            status="rejected",
            reason=validation.reason,
            risk_amount=None,
            rr_ratio=None,
        )
        context.user_data.clear()
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌  REJECTED SIGNAL\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Symbol:     {signal.symbol}\n"
            f"Direction:  {signal.direction}\n"
            f"Entry:      {signal.entry}\n"
            f"SL:         {signal.stop_loss}\n"
            f"TP:         {signal.take_profit}\n"
            f"Confidence: {signal.confidence:.0f}%\n\n"
            f"Layer:   Q Validation\n"
            f"Reason:  {validation.reason}"
        )
        await update.message.reply_text(text, reply_markup=back_keyboard())
        return ConversationHandler.END

    approved_today = get_approved_count_today()
    consecutive = get_consecutive_losses()
    risk = check_risk(approved_today, consecutive)

    if not risk.allowed:
        insert_trade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            status="rejected",
            reason=risk.reason,
            risk_amount=None,
            rr_ratio=None,
        )
        context.user_data.clear()
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌  REJECTED SIGNAL\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Symbol:     {signal.symbol}\n"
            f"Direction:  {signal.direction}\n"
            f"Entry:      {signal.entry}\n"
            f"SL:         {signal.stop_loss}\n"
            f"TP:         {signal.take_profit}\n"
            f"Confidence: {signal.confidence:.0f}%\n\n"
            f"Layer:   Q Risk Engine\n"
            f"Reason:  {risk.reason}"
        )
        await update.message.reply_text(text, reply_markup=back_keyboard())
        return ConversationHandler.END

    rr = calculate_rr(signal)
    insert_trade(
        symbol=signal.symbol,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        confidence=signal.confidence,
        status="approved",
        reason=validation.reason,
        risk_amount=risk.risk_amount,
        rr_ratio=rr,
    )
    context.user_data.clear()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅  APPROVED SIGNAL\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Symbol:      {signal.symbol}\n"
        f"Direction:   {signal.direction}\n"
        f"Entry:       {signal.entry}\n"
        f"Stop Loss:   {signal.stop_loss}\n"
        f"Take Profit: {signal.take_profit}\n"
        f"Confidence:  {signal.confidence:.0f}%\n\n"
        f"Risk Amount: ${risk.risk_amount:.0f}\n"
        f"R:R Ratio:   1:{rr}\n\n"
        f"Mode: Paper Trading"
    )
    await update.message.reply_text(text, reply_markup=back_keyboard())
    return ConversationHandler.END


async def cancel_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\n\nQ AI v2.0 — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel_signal_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\n\nQ AI v2.0 — Main Menu\nSelect an option below:",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cmd_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_trades_by_status("approved")
    if not trades:
        await update.message.reply_text("No approved trades today.", reply_markup=back_keyboard())
        return
    lines = [f"✅ Approved Trades Today — {len(trades)}\n"]
    for t in trades:
        lines.append(
            f"#{t['id']} {t['direction']} {t['symbol']}\n"
            f"   Entry: {t['entry']} | SL: {t['stop_loss']} | TP: {t['take_profit']}\n"
            f"   Confidence: {t['confidence']:.0f}% | R:R {t['rr_ratio']} | Risk: ${t['risk_amount']:.0f}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


async def cmd_rejected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_trades_by_status("rejected")
    if not trades:
        await update.message.reply_text("No rejected signals today.", reply_markup=back_keyboard())
        return
    lines = [f"❌ Rejected Signals Today — {len(trades)}\n"]
    for t in trades:
        lines.append(
            f"#{t['id']} {t['direction']} {t['symbol']}\n"
            f"   Confidence: {t['confidence']:.0f}%\n"
            f"   Reason: {t['reason']}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = get_stats_today()
    alltime = get_all_time_stats()

    def win_rate(d: dict) -> str:
        if d["total"] == 0:
            return "N/A"
        return f"{(d['approved'] / d['total']) * 100:.1f}%"

    text = (
        "📊 Q AI — Statistics\n"
        f"{'─' * 28}\n\n"
        f"Today ({date.today()})\n"
        f"  Total:     {today['total']}\n"
        f"  Approved:  {today['approved']}  ✅\n"
        f"  Rejected:  {today['rejected']}  ❌\n"
        f"  Rate:      {win_rate(today)}\n\n"
        f"All Time\n"
        f"  Total:     {alltime['total']}\n"
        f"  Approved:  {alltime['approved']}  ✅\n"
        f"  Rejected:  {alltime['rejected']}  ❌\n"
        f"  Rate:      {win_rate(alltime)}"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    approved_today = get_approved_count_today()
    consecutive = get_consecutive_losses()
    text = risk_status_text(approved_today, consecutive)
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    init_db()

    app = Application.builder().token(token).build()

    signal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(signal_start, pattern="^log_signal$")],
        states={
            SIGNAL_SYMBOL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_symbol),
            ],
            SIGNAL_DIRECTION: [
                CallbackQueryHandler(signal_direction, pattern="^dir_"),
                CallbackQueryHandler(cancel_signal_msg, pattern="^cancel_signal_msg$"),
            ],
            SIGNAL_ENTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_entry),
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
            ],
            SIGNAL_SL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_sl),
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
            ],
            SIGNAL_TP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_tp),
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
            ],
            SIGNAL_CONFIDENCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, signal_confidence),
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approved", cmd_approved))
    app.add_handler(CommandHandler("rejected", cmd_rejected))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(signal_conv)
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_risk, pattern="^risk$"))
    app.add_handler(CallbackQueryHandler(show_approved, pattern="^approved$"))
    app.add_handler(CallbackQueryHandler(show_rejected, pattern="^rejected$"))
    app.add_handler(CallbackQueryHandler(show_stats, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(show_summary, pattern="^summary$"))
    app.add_handler(CallbackQueryHandler(show_reset_confirm, pattern="^reset$"))
    app.add_handler(CallbackQueryHandler(do_reset, pattern="^reset_confirm$"))
    app.add_handler(CallbackQueryHandler(show_help, pattern="^help$"))

    logger.info("Q AI v2.0 starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
