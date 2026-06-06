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
    get_setting,
    set_setting,
    get_market_filters,
    toggle_market_filter,
    check_market_filters,
    get_open_paper_trades,
    get_paper_trades_today,
    get_all_paper_trades,
    get_performance_stats,
    get_daily_pnl_today,
)
from validator import Signal, validate_signal
from risk import check_risk, calculate_rr, risk_status_text, DEFAULT_BALANCE, get_derived
from paper_engine import open_trade, close_trade, get_balance

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
    SET_BALANCE,
) = range(7)


def current_balance() -> float:
    return get_balance()


def fmt_pnl(pnl: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return f"{sign}${pnl:,.2f}"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 Log Signal",    callback_data="log_signal"),
            InlineKeyboardButton("🌍 Market",        callback_data="market_status"),
        ],
        [
            InlineKeyboardButton("📋 Open Trades",  callback_data="open_trades"),
            InlineKeyboardButton("📊 Performance",  callback_data="performance"),
        ],
        [
            InlineKeyboardButton("✅ Approved",      callback_data="approved"),
            InlineKeyboardButton("❌ Rejected",      callback_data="rejected"),
        ],
        [
            InlineKeyboardButton("📅 Daily Report", callback_data="daily_report"),
            InlineKeyboardButton("💰 Balance",       callback_data="set_balance"),
        ],
        [
            InlineKeyboardButton("⚠️ Risk",          callback_data="risk"),
            InlineKeyboardButton("❓ Help",           callback_data="help"),
        ],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_signal")]
    ])


# ── Core screens ───────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bal = current_balance()
    filters_state = get_market_filters()
    active = [k for k, v in filters_state.items() if v]
    market_line = f"⚠️ Market Filters Active: {', '.join(active)}" if active else "🟢 Market: Clear"
    await update.message.reply_text(
        f"Welcome to Q AI.\n"
        f"Quantum Execution Intelligence System.\n"
        f"Version 3.0 — Paper Trading Engine Active\n\n"
        f"Balance: ${bal:,.2f}\n"
        f"{market_line}",
        reply_markup=main_menu_keyboard(),
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Q AI v3.0 — Main Menu", reply_markup=main_menu_keyboard()
    )


# ── Market status & filters ────────────────────────────────────────────────────

def market_status_keyboard() -> InlineKeyboardMarkup:
    f = get_market_filters()

    def label(key: str, icon_on: str, icon_off: str, name: str) -> str:
        return f"{icon_on if f[key] else icon_off} {name}: {'ACTIVE ⛔' if f[key] else 'Clear ✅'}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label("trend",      "📉", "📈", "Trend Flat"),   callback_data="toggle_trend")],
        [InlineKeyboardButton(label("volatility", "🔴", "🟢", "High Volatility"), callback_data="toggle_volatility")],
        [InlineKeyboardButton(label("news",       "📰", "📄", "News Risk"),    callback_data="toggle_news")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")],
    ])


async def show_market_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    f = get_market_filters()
    active = [k for k, v in f.items() if v]
    status_line = (
        f"⛔ {len(active)} filter(s) active — signals will be REJECTED"
        if active else "🟢 All filters clear — accepting signals"
    )
    text = (
        "🌍 Market Status — Filter Panel\n"
        f"{'─' * 32}\n\n"
        f"{status_line}\n\n"
        "Tap a filter to toggle it ON/OFF.\n"
        "Active filters block ALL new signals."
    )
    await query.edit_message_text(text, reply_markup=market_status_keyboard())


async def toggle_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.split("_", 1)[1]
    new_state = toggle_market_filter(key)
    state_word = "ACTIVE ⛔" if new_state else "Clear ✅"
    logger.info("Market filter '%s' set to %s", key, state_word)
    f = get_market_filters()
    active = [k for k, v in f.items() if v]
    status_line = (
        f"⛔ {len(active)} filter(s) active — signals will be REJECTED"
        if active else "🟢 All filters clear — accepting signals"
    )
    text = (
        "🌍 Market Status — Filter Panel\n"
        f"{'─' * 32}\n\n"
        f"{status_line}\n\n"
        "Tap a filter to toggle it ON/OFF.\n"
        "Active filters block ALL new signals."
    )
    await query.edit_message_text(text, reply_markup=market_status_keyboard())


# ── Open trades & closing ─────────────────────────────────────────────────────

def build_open_trades_keyboard(trades: list) -> InlineKeyboardMarkup:
    rows = []
    for t in trades:
        rows.append([
            InlineKeyboardButton(
                f"#{t['id']} {t['direction']} {t['symbol']} @ {t['entry']}",
                callback_data=f"noop"
            )
        ])
        rows.append([
            InlineKeyboardButton(f"✅ Win",       callback_data=f"close_{t['id']}_win"),
            InlineKeyboardButton(f"💔 Loss",      callback_data=f"close_{t['id']}_loss"),
            InlineKeyboardButton(f"➖ Breakeven", callback_data=f"close_{t['id']}_breakeven"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


async def show_open_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    trades = get_open_paper_trades()
    if not trades:
        await query.edit_message_text(
            "📋 Open Trades\n\nNo open positions.", reply_markup=back_keyboard()
        )
        return
    lines = [f"📋 Open Trades — {len(trades)} position(s)\n"]
    for t in trades:
        lines.append(
            f"#{t['id']} {t['direction']} {t['symbol']}\n"
            f"   Entry: {t['entry']} | SL: {t['stop_loss']} | TP: {t['take_profit']}\n"
            f"   R:R 1:{t['rr_ratio']} | Risk: ${t['risk_amount']:,.2f}\n"
        )
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=build_open_trades_keyboard(trades),
    )


async def handle_close_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "noop":
        return
    _, pt_id_str, result = query.data.split("_", 2)
    pt_id = int(pt_id_str)
    outcome = close_trade(pt_id, result)
    if "error" in outcome:
        await query.edit_message_text(
            f"⚠️ {outcome['error']}", reply_markup=back_keyboard()
        )
        return
    pnl = outcome["pnl"]
    result_labels = {"win": "✅ WIN", "loss": "💔 LOSS", "breakeven": "➖ BREAKEVEN"}
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏁  TRADE CLOSED — {result_labels.get(result, result.upper())}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Symbol:     {outcome['symbol']}\n"
        f"Direction:  {outcome['direction']}\n"
        f"Result:     {result_labels.get(result, result)}\n"
        f"PnL:        {fmt_pnl(pnl)}\n"
        f"Duration:   {outcome['duration_min']} min\n\n"
        f"Balance Before: ${outcome['balance_before']:,.2f}\n"
        f"Balance After:  ${outcome['balance_after']:,.2f}\n\n"
        f"Mode: Paper Trading"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


# ── Performance ────────────────────────────────────────────────────────────────

async def show_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _send_performance(query.edit_message_text)


async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_performance(update.message.reply_text)


async def _send_performance(send_fn) -> None:
    stats = get_performance_stats()
    bal = current_balance()
    starting = float(get_setting("balance_start", str(DEFAULT_BALANCE)))
    total_pnl = stats["total_pnl"]
    pct = round((total_pnl / starting) * 100, 2) if starting else 0

    pf_str = (
        f"{stats['profit_factor']:.2f}x"
        if stats["profit_factor"] != float("inf")
        else "∞"
    )

    best = stats["best_trade"]
    worst = stats["worst_trade"]
    best_line = (
        f"  Best Trade:     {fmt_pnl(best['pnl'])} ({best['direction']} {best['symbol']})"
        if best else "  Best Trade:     N/A"
    )
    worst_line = (
        f"  Worst Trade:    {fmt_pnl(worst['pnl'])} ({worst['direction']} {worst['symbol']})"
        if worst else "  Worst Trade:    N/A"
    )

    text = (
        f"📊 Performance Analytics\n"
        f"{'─' * 32}\n\n"
        f"Balance:         ${bal:,.2f}\n"
        f"Total PnL:       {fmt_pnl(total_pnl)} ({'+' if pct >= 0 else ''}{pct:.2f}%)\n\n"
        f"{'─' * 32}\n\n"
        f"Paper Trades\n"
        f"  Open:          {stats['open']}\n"
        f"  Closed:        {stats['closed']}\n"
        f"    ✅ Wins:      {stats['wins']}\n"
        f"    💔 Losses:    {stats['losses']}\n"
        f"    ➖ Breakeven: {stats['breakevens']}\n\n"
        f"Win Rate:        {stats['win_rate']:.1f}%\n"
        f"Avg Win:         ${stats['avg_win']:,.2f}\n"
        f"Avg Loss:        ${stats['avg_loss']:,.2f}\n"
        f"Profit Factor:   {pf_str}\n\n"
        f"{'─' * 32}\n\n"
        f"{best_line}\n"
        f"{worst_line}"
    )
    await send_fn(text, reply_markup=back_keyboard())


# ── Daily report ───────────────────────────────────────────────────────────────

async def show_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _send_daily_report(query.edit_message_text)


async def cmd_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_daily_report(update.message.reply_text)


async def _send_daily_report(send_fn) -> None:
    signals = get_stats_today()
    paper = get_paper_trades_today()
    open_today = [t for t in paper if t["status"] == "open"]
    closed_today = [t for t in paper if t["status"] == "closed"]
    wins = sum(1 for t in closed_today if t["result"] == "win")
    losses = sum(1 for t in closed_today if t["result"] == "loss")
    bes = sum(1 for t in closed_today if t["result"] == "breakeven")
    daily_pnl = get_daily_pnl_today()
    bal = current_balance()

    text = (
        f"📅 Daily Report — {date.today()}\n"
        f"{'─' * 34}\n\n"
        f"Signals\n"
        f"  Submitted:     {signals['total']}\n"
        f"  Approved:      {signals['approved']}  ✅\n"
        f"  Rejected:      {signals['rejected']}  ❌\n\n"
        f"Paper Trades\n"
        f"  Opened Today:  {len(paper)}\n"
        f"  Closed Today:  {len(closed_today)}\n"
        f"    ✅ Wins:      {wins}\n"
        f"    💔 Losses:    {losses}\n"
        f"    ➖ Breakeven: {bes}\n"
        f"  Still Open:    {len(open_today)}\n\n"
        f"Today's PnL:     {fmt_pnl(daily_pnl)}\n"
        f"Current Balance: ${bal:,.2f}"
    )
    await send_fn(text, reply_markup=back_keyboard())


# ── All trades list ────────────────────────────────────────────────────────────

async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_all_paper_trades()
    if not trades:
        await update.message.reply_text("No paper trades recorded.", reply_markup=main_menu_keyboard())
        return
    lines = [f"📈 All Paper Trades — {len(trades)} total\n"]
    for t in trades:
        icon = "✅" if t["result"] == "win" else "💔" if t["result"] == "loss" else ("➖" if t["result"] == "breakeven" else "🔵")
        pnl_str = fmt_pnl(t["pnl"]) if t["pnl"] is not None else "open"
        lines.append(
            f"{icon} #{t['id']} {t['direction']} {t['symbol']} @ {t['entry']} — {pnl_str}"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


async def cmd_open_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_open_paper_trades()
    if not trades:
        await update.message.reply_text("No open positions.", reply_markup=main_menu_keyboard())
        return
    lines = [f"📋 Open Trades — {len(trades)}\n"]
    for t in trades:
        lines.append(
            f"#{t['id']} {t['direction']} {t['symbol']} @ {t['entry']}\n"
            f"   SL: {t['stop_loss']} | TP: {t['take_profit']} | R:R 1:{t['rr_ratio']}\n"
            f"   Risk: ${t['risk_amount']:,.2f}\n"
        )
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=build_open_trades_keyboard(trades),
    )


async def cmd_market_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    f = get_market_filters()
    active = [k for k, v in f.items() if v]
    status_line = (
        f"⛔ {len(active)} filter(s) active — signals being REJECTED"
        if active else "🟢 All filters clear — accepting signals"
    )
    text = (
        "🌍 Market Status\n"
        f"{'─' * 26}\n\n"
        f"{status_line}\n\n"
        f"Trend Flat:      {'ACTIVE ⛔' if f['trend'] else 'Clear ✅'}\n"
        f"High Volatility: {'ACTIVE ⛔' if f['volatility'] else 'Clear ✅'}\n"
        f"News Risk:       {'ACTIVE ⛔' if f['news'] else 'Clear ✅'}\n\n"
        "Use the 🌍 Market button to toggle filters."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


# ── Risk ───────────────────────────────────────────────────────────────────────

async def show_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    bal = current_balance()
    text = risk_status_text(get_approved_count_today(), get_consecutive_losses(), bal)
    await query.edit_message_text(text, reply_markup=back_keyboard())


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bal = current_balance()
    text = risk_status_text(get_approved_count_today(), get_consecutive_losses(), bal)
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


# ── Approved / Rejected ────────────────────────────────────────────────────────

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
                f"   Confidence: {t['confidence']:.0f}% | R:R {t['rr_ratio']} | Risk: ${t['risk_amount']:,.2f}\n"
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


async def cmd_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_trades_by_status("approved")
    if not trades:
        await update.message.reply_text("No approved trades today.", reply_markup=main_menu_keyboard())
        return
    lines = [f"✅ Approved Trades Today — {len(trades)}\n"]
    for t in trades:
        lines.append(
            f"#{t['id']} {t['direction']} {t['symbol']}\n"
            f"   Entry: {t['entry']} | SL: {t['stop_loss']} | TP: {t['take_profit']}\n"
            f"   Confidence: {t['confidence']:.0f}% | R:R {t['rr_ratio']} | Risk: ${t['risk_amount']:,.2f}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


async def cmd_rejected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trades = get_trades_by_status("rejected")
    if not trades:
        await update.message.reply_text("No rejected signals today.", reply_markup=main_menu_keyboard())
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

    def ar(d: dict) -> str:
        return "N/A" if d["total"] == 0 else f"{(d['approved'] / d['total']) * 100:.1f}%"

    text = (
        f"📊 Q AI — Statistics\n{'─' * 28}\n\n"
        f"Today ({date.today()})\n"
        f"  Total:     {today['total']}\n"
        f"  Approved:  {today['approved']}  ✅\n"
        f"  Rejected:  {today['rejected']}  ❌\n"
        f"  Rate:      {ar(today)}\n\n"
        f"All Time\n"
        f"  Total:     {alltime['total']}\n"
        f"  Approved:  {alltime['approved']}  ✅\n"
        f"  Rejected:  {alltime['rejected']}  ❌\n"
        f"  Rate:      {ar(alltime)}"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


# ── Reset ──────────────────────────────────────────────────────────────────────

async def show_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚠️ Reset today's session?\n\n"
        "Clears daily risk counters and consecutive loss tracker.\n"
        "SQLite trade history and paper trades are preserved.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data="reset_confirm"),
                InlineKeyboardButton("❌ Cancel",  callback_data="main_menu"),
            ]
        ]),
    )


async def do_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ Day reset complete. Risk counters cleared.",
        reply_markup=back_keyboard(),
    )


# ── Help ───────────────────────────────────────────────────────────────────────

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    bal = current_balance()
    rpt, mdl = get_derived(bal)
    text = (
        "Q AI v3.0 — Help\n\n"
        "📡 Log Signal — Submit a 6-field signal\n"
        "🌍 Market — Toggle market filters\n"
        "📋 Open Trades — View & close open positions\n"
        "📊 Performance — Full analytics dashboard\n"
        "✅ Approved / ❌ Rejected — Today's signals\n"
        "📅 Daily Report — Full day summary\n"
        "💰 Balance — Update paper trading balance\n"
        "⚠️ Risk — Risk engine status\n\n"
        "Signal Flow:\n"
        "  1. Market filters checked first\n"
        "  2. Q Validation Layer\n"
        "  3. Q Risk Engine\n"
        "  4. Paper trade created on approval\n\n"
        f"Risk Engine (Balance: ${bal:,.2f})\n"
        f"  • ${rpt:,.2f} per trade (1%)\n"
        f"  • Max 3 trades/day | 5% daily loss\n"
        f"  • Pause after 3 consecutive losses\n\n"
        "Commands:\n"
        "/approved /rejected /stats /risk\n"
        "/performance /trades /open_trades\n"
        "/daily_report /market_status /setbalance\n\n"
        "Mode: Paper Trading Only"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())


# ── Set balance ────────────────────────────────────────────────────────────────

async def balance_start_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    bal = current_balance()
    await query.edit_message_text(
        f"💰 Set Paper Trading Balance\n\n"
        f"Current Balance: ${bal:,.2f}\n\n"
        f"Enter the new balance (e.g. 25000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_balance")]
        ]),
    )
    return SET_BALANCE


async def balance_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bal = current_balance()
    await update.message.reply_text(
        f"💰 Set Paper Trading Balance\n\n"
        f"Current Balance: ${bal:,.2f}\n\n"
        f"Enter the new balance (e.g. 25000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_balance")]
        ]),
    )
    return SET_BALANCE


async def balance_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_bal = float(update.message.text.strip().replace(",", ""))
        if new_bal <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Invalid amount. Enter a positive number:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_balance")]
            ]),
        )
        return SET_BALANCE
    old_bal = current_balance()
    set_setting("balance", str(new_bal))
    set_setting("balance_start", str(new_bal))
    rpt, mdl = get_derived(new_bal)
    await update.message.reply_text(
        f"💰 Balance Updated\n{'─' * 26}\n\n"
        f"Previous:        ${old_bal:,.2f}\n"
        f"New Balance:     ${new_bal:,.2f}\n\n"
        f"Risk Per Trade:  ${rpt:,.2f} (1%)\n"
        f"Max Daily Loss:  ${mdl:,.2f} (5%)\n\n"
        f"Q Risk Engine recalculated.",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


async def cancel_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Cancelled.\n\nQ AI v3.0 — Main Menu",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ── Signal flow ────────────────────────────────────────────────────────────────

async def signal_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    blocked, reason = check_market_filters()
    if blocked:
        await query.edit_message_text(
            f"⛔ Signal Blocked\n\n{reason}\n\n"
            f"Disable the filter via 🌍 Market to resume.",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "📡 Q Signal Logger — Step 1 of 6\n\nEnter the symbol (e.g. AAPL, TSLA, BTCUSD):",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_SYMBOL


async def signal_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 2 of 6\n\nSymbol: {context.user_data['symbol']}\n\nChoose direction:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 BUY",  callback_data="dir_BUY"),
                InlineKeyboardButton("📉 SELL", callback_data="dir_SELL"),
            ],
            [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_signal_msg")],
        ]),
    )
    return SIGNAL_DIRECTION


async def signal_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["direction"] = query.data.split("_")[1]
    await query.edit_message_text(
        f"📡 Q Signal Logger — Step 3 of 6\n\n"
        f"Symbol: {context.user_data['symbol']} | {context.user_data['direction']}\n\nEnter Entry Price:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_ENTRY


async def _get_float(update: Update, key: str, label: str, next_prompt: str, next_state: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data[key] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid price. Enter a number:", reply_markup=cancel_keyboard())
        return next_state - 1  # stay in current state (caller adjusts)
    await update.message.reply_text(next_prompt, reply_markup=cancel_keyboard())
    return next_state


async def signal_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["entry"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid price. Enter a number:", reply_markup=cancel_keyboard())
        return SIGNAL_ENTRY
    d = context.user_data
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 4 of 6\n\n"
        f"Symbol: {d['symbol']} | {d['direction']}\nEntry: {d['entry']}\n\nEnter Stop Loss:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_SL


async def signal_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["stop_loss"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid price. Enter a number:", reply_markup=cancel_keyboard())
        return SIGNAL_SL
    d = context.user_data
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 5 of 6\n\n"
        f"Symbol: {d['symbol']} | {d['direction']}\nEntry: {d['entry']} | SL: {d['stop_loss']}\n\nEnter Take Profit:",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_TP


async def signal_tp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["take_profit"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid price. Enter a number:", reply_markup=cancel_keyboard())
        return SIGNAL_TP
    d = context.user_data
    await update.message.reply_text(
        f"📡 Q Signal Logger — Step 6 of 6\n\n"
        f"Symbol: {d['symbol']} | {d['direction']}\n"
        f"Entry: {d['entry']} | SL: {d['stop_loss']} | TP: {d['take_profit']}\n\nEnter Confidence Score (0–100):",
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
            "Invalid score. Enter a number between 0 and 100:", reply_markup=cancel_keyboard()
        )
        return SIGNAL_CONFIDENCE

    context.user_data["confidence"] = confidence
    d = context.user_data
    signal = Signal(
        symbol=d["symbol"], direction=d["direction"],
        entry=d["entry"], stop_loss=d["stop_loss"],
        take_profit=d["take_profit"], confidence=d["confidence"],
    )
    context.user_data.clear()

    # Layer 1 — Q Validation
    validation = validate_signal(signal)
    if not validation.valid:
        insert_trade(
            symbol=signal.symbol, direction=signal.direction,
            entry=signal.entry, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit, confidence=signal.confidence,
            status="rejected", reason=validation.reason,
            risk_amount=None, rr_ratio=None,
        )
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❌  REJECTED SIGNAL\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Symbol:     {signal.symbol}\n"
            f"Direction:  {signal.direction}\n"
            f"Entry:      {signal.entry}\n"
            f"SL:         {signal.stop_loss}\n"
            f"TP:         {signal.take_profit}\n"
            f"Confidence: {signal.confidence:.0f}%\n\n"
            f"Layer:   Q Validation\n"
            f"Reason:  {validation.reason}",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    # Layer 2 — Q Risk Engine
    bal = current_balance()
    risk = check_risk(get_approved_count_today(), get_consecutive_losses(), bal)
    if not risk.allowed:
        insert_trade(
            symbol=signal.symbol, direction=signal.direction,
            entry=signal.entry, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit, confidence=signal.confidence,
            status="rejected", reason=risk.reason,
            risk_amount=None, rr_ratio=None,
        )
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❌  REJECTED SIGNAL\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Symbol:     {signal.symbol}\n"
            f"Direction:  {signal.direction}\n"
            f"Entry:      {signal.entry}\n"
            f"SL:         {signal.stop_loss}\n"
            f"TP:         {signal.take_profit}\n"
            f"Confidence: {signal.confidence:.0f}%\n\n"
            f"Layer:   Q Risk Engine\n"
            f"Reason:  {risk.reason}",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    # Approved — record signal + open paper trade
    rr = calculate_rr(signal)
    signal_id = insert_trade(
        symbol=signal.symbol, direction=signal.direction,
        entry=signal.entry, stop_loss=signal.stop_loss,
        take_profit=signal.take_profit, confidence=signal.confidence,
        status="approved", reason=validation.reason,
        risk_amount=risk.risk_amount, rr_ratio=rr,
    )
    pt_id = open_trade(
        signal_id=signal_id, symbol=signal.symbol, direction=signal.direction,
        entry=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
        risk_amount=risk.risk_amount, rr_ratio=rr,
    )
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅  APPROVED SIGNAL\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Symbol:      {signal.symbol}\n"
        f"Direction:   {signal.direction}\n"
        f"Entry:       {signal.entry}\n"
        f"Stop Loss:   {signal.stop_loss}\n"
        f"Take Profit: {signal.take_profit}\n"
        f"Confidence:  {signal.confidence:.0f}%\n\n"
        f"Balance:     ${bal:,.2f}\n"
        f"Risk Amount: ${risk.risk_amount:,.2f}\n"
        f"R:R Ratio:   1:{rr}\n\n"
        f"📋 Paper Trade #{pt_id} opened.\n"
        f"Close it via 📋 Open Trades.\n\n"
        f"Mode: Paper Trading",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


async def cancel_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\n\nQ AI v3.0 — Main Menu",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel_signal_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\n\nQ AI v3.0 — Main Menu",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ── App entry ──────────────────────────────────────────────────────────────────

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
                CallbackQueryHandler(cancel_signal, pattern="^cancel_signal$"),
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

    balance_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(balance_start_btn, pattern="^set_balance$"),
            CommandHandler("setbalance", balance_start_cmd),
        ],
        states={
            SET_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, balance_input),
                CallbackQueryHandler(cancel_balance, pattern="^cancel_balance$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    # Commands
    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("approved",      cmd_approved))
    app.add_handler(CommandHandler("rejected",      cmd_rejected))
    app.add_handler(CommandHandler("stats",         cmd_stats))
    app.add_handler(CommandHandler("risk",          cmd_risk))
    app.add_handler(CommandHandler("performance",   cmd_performance))
    app.add_handler(CommandHandler("trades",        cmd_trades))
    app.add_handler(CommandHandler("open_trades",   cmd_open_trades))
    app.add_handler(CommandHandler("daily_report",  cmd_daily_report))
    app.add_handler(CommandHandler("market_status", cmd_market_status))

    # Conversations
    app.add_handler(signal_conv)
    app.add_handler(balance_conv)

    # Button callbacks
    app.add_handler(CallbackQueryHandler(show_main_menu,    pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_risk,         pattern="^risk$"))
    app.add_handler(CallbackQueryHandler(show_approved,     pattern="^approved$"))
    app.add_handler(CallbackQueryHandler(show_rejected,     pattern="^rejected$"))
    app.add_handler(CallbackQueryHandler(show_performance,  pattern="^performance$"))
    app.add_handler(CallbackQueryHandler(show_open_trades,  pattern="^open_trades$"))
    app.add_handler(CallbackQueryHandler(show_daily_report, pattern="^daily_report$"))
    app.add_handler(CallbackQueryHandler(show_market_status,pattern="^market_status$"))
    app.add_handler(CallbackQueryHandler(show_reset_confirm,pattern="^reset$"))
    app.add_handler(CallbackQueryHandler(do_reset,          pattern="^reset_confirm$"))
    app.add_handler(CallbackQueryHandler(show_help,         pattern="^help$"))
    app.add_handler(CallbackQueryHandler(toggle_filter,     pattern="^toggle_(trend|volatility|news)$"))
    app.add_handler(CallbackQueryHandler(handle_close_trade,pattern=r"^close_\d+_(win|loss|breakeven)$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))

    logger.info("Q AI v3.0 — Paper Trading Engine starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
