import os
import sys
import logging
import warnings
import asyncio

from dotenv import load_dotenv
load_dotenv()
from server import start as start_server

from mt5_client import get_mt5_status, get_mt5_account, get_mt5_positions, get_mt5_price, is_mt5_connected

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
    add_alert_chat,
    remove_alert_chat,
    get_alert_chats,
)
from validator import Signal, validate_signal
from risk import check_risk, calculate_rr, risk_status_text, DEFAULT_BALANCE, get_derived
from paper_engine import open_trade, close_trade, get_balance
from market_data import (
    is_api_configured, fetch_prices_batch, format_price, fetch_candles_batch,
)
from signal_engine import scan_markets, MarketSignal, get_technical_summary
from chart import generate_equity_chart
from watchlist import (
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    reset_watchlist, group_by_market, get_market_type,
    MARKET_ICONS, MARKET_LABELS, normalise as normalise_symbol,
    DEFAULT_WATCHLIST,
)

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
            InlineKeyboardButton("🔭 Scanner",       callback_data="scanner"),
        ],
        [
            InlineKeyboardButton("📈 Markets",       callback_data="markets"),
            InlineKeyboardButton("👁️ Watchlist",     callback_data="watchlist"),
        ],
        [
            InlineKeyboardButton("📋 Open Trades",   callback_data="open_trades"),
            InlineKeyboardButton("📊 Performance",   callback_data="performance"),
        ],
        [
            InlineKeyboardButton("📅 Daily Report",  callback_data="daily_report"),
            InlineKeyboardButton("⚠️ Risk",           callback_data="risk"),
        ],
        [
            InlineKeyboardButton("✅ Approved",       callback_data="approved"),
            InlineKeyboardButton("❌ Rejected",       callback_data="rejected"),
        ],
        [
            InlineKeyboardButton("💰 Balance",       callback_data="set_balance"),
            InlineKeyboardButton("🌐 Filters",       callback_data="market_status"),
        ],
        [
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
        f"Welcome to Qubit.\n"
        f"Analyze. Validate. Execute.\n"
        f"Version 3.0 — Paper Trading Engine Active\n\n"
        f"Balance: ${bal:,.2f}\n"
        f"{market_line}",
        reply_markup=main_menu_keyboard(),
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Qubit v3.0 — Main Menu", reply_markup=main_menu_keyboard()
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
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Equity Chart", callback_data="equity_chart")],
        [InlineKeyboardButton("⬅️ Main Menu",    callback_data="main_menu")],
    ])
    await send_fn(text, reply_markup=keyboard)


# ── Equity chart ────────────────────────────────────────────────────────────────

async def _send_chart(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate the equity chart and send it as a photo."""
    import asyncio
    loop = asyncio.get_event_loop()
    buf = await loop.run_in_executor(None, generate_equity_chart)

    if buf is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "📊 No data yet\n\n"
                "Equity chart appears after your first closed paper trade.\n\n"
                "Tip: close an open trade via 📋 Open Trades → win / loss / breakeven"
            ),
            reply_markup=back_keyboard(),
        )
        return

    stats       = get_performance_stats()
    bal         = get_balance()
    total_pnl   = stats["total_pnl"]
    pnl_sign    = "+" if total_pnl >= 0 else ""
    win_rate    = stats["win_rate"]

    caption = (
        f"📈 Qubit — Equity Curve\n"
        f"Balance: ${bal:,.2f}  |  PnL: {pnl_sign}${total_pnl:,.2f}  |  "
        f"Win Rate: {win_rate:.1f}%  |  "
        f"Trades: {stats['closed']} closed"
    )
    await context.bot.send_photo(chat_id=chat_id, photo=buf, caption=caption)


async def show_chart_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 📈 Equity Chart button."""
    query = update.callback_query
    await query.answer("Generating chart…")
    await _send_chart(query.message.chat_id, context)


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chart — send the equity curve chart."""
    msg = await update.message.reply_text("📊 Generating equity chart…")
    await _send_chart(update.effective_chat.id, context)
    try:
        await msg.delete()
    except Exception:
        pass


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


async def cmd_mt5(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_mt5_status()
    if data.get("error"):
        await update.message.reply_text(f"❌ MT5 Bridge\n\n{data['error']}")
        return
    await update.message.reply_text(
        f"✅ MT5 Connected\n"
        f"Server: {data.get('server')}\n"
        f"Login:  {data.get('login')}"
    )


async def cmd_mt5account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_mt5_account()
    if data.get("error"):
        await update.message.reply_text(f"❌ MT5 Account Error\n\n{data['error']}")
        return
    await update.message.reply_text(
        f"💼 MT5 Account\n{'─'*26}\n"
        f"Name:         {data['name']}\n"
        f"Server:       {data['server']}\n"
        f"Balance:      ${data['balance']:,.2f}\n"
        f"Equity:       ${data['equity']:,.2f}\n"
        f"Margin:       ${data['margin']:,.2f}\n"
        f"Free Margin:  ${data['free_margin']:,.2f}\n"
        f"Profit:       ${data['profit']:,.2f}\n"
        f"Leverage:     1:{data['leverage']}\n"
        f"Currency:     {data['currency']}"
    )


async def cmd_mt5positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_mt5_positions()
    if data.get("error"):
        await update.message.reply_text(f"❌ MT5 Error\n\n{data['error']}")
        return
    positions = data.get("positions", [])
    if not positions:
        await update.message.reply_text("📋 MT5 Positions\n\nNo open positions.")
        return
    lines = [f"📋 MT5 Positions — {len(positions)}\n"]
    for p in positions:
        lines.append(
            f"#{p['ticket']} {p['type']} {p['symbol']}\n"
            f"   Vol: {p['volume']} | Open: {p['open_price']} → {p['current_price']}\n"
            f"   SL: {p['sl']} | TP: {p['tp']} | P&L: ${p['profit']:,.2f}\n"
        )
    await update.message.reply_text("\n".join(lines))


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
        f"📊 Qubit — Statistics\n{'─' * 28}\n\n"
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
        "Qubit v3.0 — Help\n\n"
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
        "  2. Qubit Analytics (QA)\n"
        "  3. Qubit Risk (QR)\n"
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
        f"Qubit Risk (QR) recalculated.",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


async def cancel_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Cancelled.\n\nQubit v3.0 — Main Menu",
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
        "📡 Signal Logger — Step 1 of 6\n\nEnter the symbol (e.g. AAPL, TSLA, BTCUSD):",
        reply_markup=cancel_keyboard(),
    )
    return SIGNAL_SYMBOL


async def signal_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["symbol"] = update.message.text.strip().upper()
    await update.message.reply_text(
        f"📡 Signal Logger — Step 2 of 6\n\nSymbol: {context.user_data['symbol']}\n\nChoose direction:",
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
        f"📡 Signal Logger — Step 3 of 6\n\n"
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
        f"📡 Signal Logger — Step 4 of 6\n\n"
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
        f"📡 Signal Logger — Step 5 of 6\n\n"
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
        f"📡 Signal Logger — Step 6 of 6\n\n"
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

    # Layer 1 — Qubit Analytics (QA)
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
            f"Layer:   Qubit Analytics (QA)\n"
            f"Reason:  {validation.reason}",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    # Layer 2 — Qubit Risk (QR)
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
            f"Layer:   Qubit Risk (QR)\n"
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
        "Signal cancelled.\n\nQubit v3.0 — Main Menu",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel_signal_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "Signal cancelled.\n\nQubit v3.0 — Main Menu",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ── Multi-market: Markets overview ────────────────────────────────────────────

def _markets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔭 Run Scanner", callback_data="scanner"),
            InlineKeyboardButton("👁️ Watchlist",   callback_data="watchlist"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu",      callback_data="main_menu")],
    ])


async def _do_markets(reply_fn, context: ContextTypes.DEFAULT_TYPE) -> None:
    import asyncio
    wl     = get_watchlist()
    loop   = asyncio.get_event_loop()
    prices = await loop.run_in_executor(None, lambda: fetch_prices_batch(wl))

    groups = group_by_market(wl)
    lines: list[str] = [f"📈 QUBIT MARKETS\n{'━' * 28}\n"]

    for mtype in ("forex", "stock", "crypto", "unknown"):
        syms = groups.get(mtype, [])
        if not syms:
            continue
        lines.append(f"{MARKET_ICONS[mtype]} {MARKET_LABELS[mtype]}")
        for sym in syms:
            p = prices.get(sym)
            if isinstance(p, Exception):
                lines.append(f"  {sym:<10}  —")
            else:
                lines.append(f"  {sym:<10}  {format_price(p, sym)}")
        lines.append("")

    lines.append(f"Symbols: {len(wl)}  |  Use 🔭 Scanner for signals")
    text = "\n".join(lines).strip()
    await reply_fn(text, reply_markup=_markets_keyboard())


async def show_markets_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_api_configured():
        await query.edit_message_text(
            "⚠️ TWELVE_DATA_API_KEY not configured.",
            reply_markup=back_keyboard(),
        )
        return
    await query.edit_message_text("📈 Fetching live prices… please wait")
    await _do_markets(query.edit_message_text, context)


async def cmd_markets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_api_configured():
        await update.message.reply_text(
            "⚠️ TWELVE_DATA_API_KEY not configured.",
            reply_markup=main_menu_keyboard(),
        )
        return
    msg = await update.message.reply_text("📈 Fetching live prices… please wait")
    await _do_markets(msg.edit_text, context)


# ── Multi-market: Watchlist ────────────────────────────────────────────────────

def _watchlist_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Reset to Defaults", callback_data="wl_reset")],
        [
            InlineKeyboardButton("📈 Markets",  callback_data="markets"),
            InlineKeyboardButton("🔭 Scanner",  callback_data="scanner"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")],
    ])


async def _show_watchlist_text(send_fn) -> None:
    wl     = get_watchlist()
    groups = group_by_market(wl)
    lines: list[str] = [f"👁️ WATCHLIST  ({len(wl)} symbols)\n{'━' * 28}\n"]

    for mtype in ("forex", "stock", "crypto", "unknown"):
        syms = groups.get(mtype, [])
        if not syms:
            continue
        lines.append(f"{MARKET_ICONS[mtype]} {MARKET_LABELS[mtype]}")
        lines.append("  " + "  •  ".join(syms))
        lines.append("")

    lines += [
        "── Manage ──────────────────",
        "/watchlist add SYMBOL",
        "/watchlist remove SYMBOL",
        "/watchlist reset",
        "",
        "Examples:",
        "  /watchlist add MSFT",
        "  /watchlist add SOLUSD",
        "  /watchlist remove USDJPY",
    ]
    await send_fn("\n".join(lines), reply_markup=_watchlist_keyboard())


async def show_watchlist_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _show_watchlist_text(query.edit_message_text)


async def do_wl_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    reset_watchlist()
    await _show_watchlist_text(query.edit_message_text)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []

    if not args:
        await _show_watchlist_text(update.message.reply_text)
        return

    sub = args[0].lower()

    if sub == "reset":
        reset_watchlist()
        await update.message.reply_text(
            "✅ Watchlist reset to defaults.\n\n"
            + "  ".join(DEFAULT_WATCHLIST),
            reply_markup=main_menu_keyboard(),
        )
        return

    if sub in ("add", "remove") and len(args) < 2:
        await update.message.reply_text(
            f"Usage: /watchlist {sub} SYMBOL\nExample: /watchlist {sub} MSFT",
            reply_markup=main_menu_keyboard(),
        )
        return

    if sub == "add":
        ok, msg = add_to_watchlist(args[1])
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
        return

    if sub == "remove":
        ok, msg = remove_from_watchlist(args[1])
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
        return

    await _show_watchlist_text(update.message.reply_text)


# ── Multi-market: Analyze ─────────────────────────────────────────────────────

def format_analysis_text(symbol: str, summary: dict) -> str:
    mtype = get_market_type(symbol)
    icon  = MARKET_ICONS.get(mtype, "❓")
    label = MARKET_LABELS.get(mtype, "Unknown")

    trend_icon = "📈" if summary["trend"] == "bullish" else "📉"
    rsi = summary["rsi"]
    if rsi < 30:
        rsi_label = "Oversold 🔴"
    elif rsi < 40:
        rsi_label = "Near Oversold"
    elif rsi > 70:
        rsi_label = "Overbought 🔴"
    elif rsi > 60:
        rsi_label = "Near Overbought ⚠️"
    else:
        rsi_label = "Neutral ✅"

    sig = summary.get("signal")
    text = (
        f"🔬 ANALYSIS: {symbol}\n"
        f"{'━' * 28}\n"
        f"Price:        {format_price(summary['price'], symbol)}\n"
        f"Market:       {icon} {label}\n\n"
        f"── Technical Indicators ──\n"
        f"EMA 20:       {summary['ema20']}\n"
        f"EMA 50:       {summary['ema50']}\n"
        f"Trend:        {trend_icon} {summary['crossover']}\n"
        f"RSI (14):     {rsi} — {rsi_label}\n"
        f"EMA Gap:      {summary['ema_sep']:.3f}%\n"
        f"10-Bar High:  {summary['recent_high']}\n"
        f"10-Bar Low:   {summary['recent_low']}\n\n"
    )
    if sig:
        action_icon = "📈 BUY" if sig.action == "BUY" else "📉 SELL"
        cross = "Fresh crossover ✅" if sig.crossover else "Trend continuation"
        text += (
            f"── Signal ────────────────\n"
            f"Direction:    {action_icon}\n"
            f"Confidence:   {sig.confidence:.0f}%\n"
            f"Entry:        {sig.entry}\n"
            f"SL:           {sig.sl}\n"
            f"TP:           {sig.tp}\n"
            f"Setup:        {cross}"
        )
    else:
        text += (
            "── Signal ────────────────\n"
            "No clear signal at this time.\n"
            "Market is neutral / consolidating."
        )
    return text


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_api_configured():
        await update.message.reply_text(
            "⚠️ TWELVE_DATA_API_KEY not configured.",
            reply_markup=main_menu_keyboard(),
        )
        return

    args = context.args or []
    if not args:
        wl = get_watchlist()
        ex = wl[0] if wl else "EURUSD"
        await update.message.reply_text(
            f"🔬 Qubit Analytics — Symbol Analysis\n\n"
            f"Usage: /analyze SYMBOL\n\n"
            f"Examples:\n"
            f"  /analyze {ex}\n"
            f"  /analyze AAPL\n"
            f"  /analyze BTCUSD\n\n"
            f"Watchlist: {', '.join(wl)}",
            reply_markup=main_menu_keyboard(),
        )
        return

    symbol = normalise_symbol(args[0])
    msg = await update.message.reply_text(
        f"🔬 Analyzing {symbol}… please wait (up to 10 s)"
    )

    import asyncio
    loop = asyncio.get_event_loop()
    try:
        batch = await loop.run_in_executor(
            None, lambda: fetch_candles_batch([symbol], outputsize=60)
        )
        candles = batch[symbol]
        if isinstance(candles, Exception):
            raise candles
    except Exception as exc:
        await msg.edit_text(
            f"❌ Could not fetch data for {symbol}\n\n{exc}",
            reply_markup=back_keyboard(),
        )
        return

    summary = get_technical_summary(symbol, candles)
    if summary is None:
        await msg.edit_text(
            f"⚠️ Insufficient data for {symbol} — need at least 52 candles.",
            reply_markup=back_keyboard(),
        )
        return

    text = format_analysis_text(symbol, summary)
    sig  = summary.get("signal")
    keyboard = logsig_keyboard(sig) if sig else back_keyboard()
    await msg.edit_text(text, reply_markup=keyboard)


# ── Market scan helpers ────────────────────────────────────────────────────────

def _sig_callback(sig: MarketSignal) -> str:
    """Encode signal into callback_data (always under 64 bytes)."""
    return f"logsig_{sig.symbol}_{sig.action}_{sig.entry}_{sig.sl}_{sig.tp}_{sig.confidence}"


def format_signal_message(sig: MarketSignal, auto: bool = False) -> str:
    header = "🤖 AUTO-SIGNAL" if auto else "🔔 QUBIT SIGNAL"
    cross_label = "Fresh crossover ✅" if sig.crossover else "Trend continuation"
    if sig.rsi < 35:
        rsi_zone = "Oversold ⚠️"
    elif sig.rsi > 65:
        rsi_zone = "Overbought ⚠️"
    else:
        rsi_zone = "Neutral ✅"
    action_icon = "📈 BUY" if sig.action == "BUY" else "📉 SELL"
    return (
        f"{header}\n"
        f"{'━' * 28}\n"
        f"PAIR:        {sig.symbol}\n"
        f"PRICE:       {sig.price}\n"
        f"ACTION:      {action_icon}\n"
        f"ENTRY:       {sig.entry}\n"
        f"SL:          {sig.sl}\n"
        f"TP:          {sig.tp}\n"
        f"CONFIDENCE:  {sig.confidence}%\n"
        f"{'━' * 28}\n"
        f"EMA20/50:   {cross_label}\n"
        f"RSI(14):    {sig.rsi} — {rsi_zone}\n"
        f"Interval:   {sig.interval}\n"
        f"Mode:       Paper Trading"
    )


def logsig_keyboard(sig: MarketSignal) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Log as Paper Trade", callback_data=_sig_callback(sig))],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")],
    ])


async def _do_scan(chat_id: int, context: ContextTypes.DEFAULT_TYPE, reply_fn) -> None:
    """
    Core scan logic shared by /scan command and the Scan Markets button.
    reply_fn: async callable for the first reply (edit_message_text or msg.edit_text).
    Additional signals go via context.bot.send_message(chat_id).
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, scan_markets)
    except Exception as exc:
        await reply_fn(f"❌ Scan failed: {exc}", reply_markup=back_keyboard())
        return

    signals  = [(sym, sig) for sym, sig in results if isinstance(sig, MarketSignal)]
    no_signal = [sym for sym, sig in results if sig is None]
    errors   = [(sym, err) for sym, err in results if isinstance(err, Exception)]

    if not signals:
        no_sig_str = ", ".join(no_signal) if no_signal else "—"
        err_str = "\n".join(f"• {s}: {e}" for s, e in errors) or "  None"
        note = f"\n\nErrors:\n{err_str}" if errors else ""
        await reply_fn(
            f"🔍 Market Scan Complete\n\n"
            f"No actionable signals detected.\n"
            f"Pairs scanned: {no_sig_str}{note}",
            reply_markup=back_keyboard(),
        )
        return

    # First signal — replace the "Scanning..." message
    _, first_sig = signals[0]
    await reply_fn(format_signal_message(first_sig), reply_markup=logsig_keyboard(first_sig))

    # Additional signals — new messages
    for _, sig in signals[1:]:
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_signal_message(sig),
            reply_markup=logsig_keyboard(sig),
        )

    # Footer summary
    no_sig_str = f" | No signal: {', '.join(no_signal)}" if no_signal else ""
    if len(signals) > 1 or no_signal:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔍 Scan done — {len(signals)} signal(s) found{no_sig_str}",
            reply_markup=back_keyboard(),
        )


async def show_scan_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 🔍 Scan Markets button from main menu."""
    query = update.callback_query
    await query.answer()
    if not is_api_configured():
        await query.edit_message_text(
            "⚠️ Market scan unavailable\n\n"
            "TWELVE_DATA_API_KEY is not configured.\n"
            "Add it to Replit Secrets and restart the bot.",
            reply_markup=back_keyboard(),
        )
        return
    await query.edit_message_text("🔍 Scanning markets… please wait (up to 10 s)")
    await _do_scan(
        chat_id=query.message.chat_id,
        context=context,
        reply_fn=query.edit_message_text,
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/scan — manually trigger a live market scan."""
    if not is_api_configured():
        await update.message.reply_text(
            "⚠️ TWELVE_DATA_API_KEY not configured.\n"
            "Add it to Replit Secrets and restart the bot.",
            reply_markup=main_menu_keyboard(),
        )
        return
    msg = await update.message.reply_text("🔍 Scanning markets… please wait (up to 10 s)")
    await _do_scan(
        chat_id=update.effective_chat.id,
        context=context,
        reply_fn=msg.edit_text,
    )


async def cmd_setchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setchat — register this chat for auto-scan alerts and enable auto-scan."""
    if not is_api_configured():
        await update.message.reply_text(
            "⚠️ Cannot register: TWELVE_DATA_API_KEY not configured.",
            reply_markup=main_menu_keyboard(),
        )
        return
    chat_id = update.effective_chat.id
    add_alert_chat(chat_id)
    set_setting("autoscan_enabled", "1")
    await update.message.reply_text(
        f"✅ Chat registered for auto-scan alerts.\n\n"
        f"Chat ID:    {chat_id}\n"
        f"Auto-scan:  ON (every 10 min)\n\n"
        f"Qubit will post live signals here automatically.\n"
        f"Use /autoscan off to stop.",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_autoscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/autoscan on|off — toggle auto-scan for this chat."""
    args = context.args or []
    chat_id = update.effective_chat.id

    if not args or args[0].lower() not in ("on", "off"):
        status = "ON ✅" if get_setting("autoscan_enabled", "0") == "1" else "OFF 🔴"
        chats = get_alert_chats()
        await update.message.reply_text(
            f"📡 Auto-Scan Status: {status}\n"
            f"Registered chats: {len(chats)}\n"
            f"Scan interval: every 10 minutes\n\n"
            f"Usage:\n"
            f"  /autoscan on  — enable & register this chat\n"
            f"  /autoscan off — disable & unregister this chat\n\n"
            f"Tip: /setchat does the same as /autoscan on",
            reply_markup=main_menu_keyboard(),
        )
        return

    if args[0].lower() == "on":
        if not is_api_configured():
            await update.message.reply_text(
                "⚠️ Cannot enable: TWELVE_DATA_API_KEY not configured.",
                reply_markup=main_menu_keyboard(),
            )
            return
        add_alert_chat(chat_id)
        set_setting("autoscan_enabled", "1")
        await update.message.reply_text(
            "✅ Auto-Scan ENABLED\n\n"
            "Qubit will scan all 4 pairs every 10 minutes.\n"
            "Signals will be posted here automatically.\n\n"
            "Use /autoscan off to stop.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        remove_alert_chat(chat_id)
        if not get_alert_chats():
            set_setting("autoscan_enabled", "0")
        await update.message.reply_text(
            "🔴 Auto-Scan DISABLED\n\nNo more automatic signals for this chat.",
            reply_markup=main_menu_keyboard(),
        )


async def handle_log_autosignal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles 'Log as Paper Trade' button on a scan signal.
    Callback data: logsig_{symbol}_{action}_{entry}_{sl}_{tp}_{conf}
    Runs through QA validation + QR risk check before logging.
    """
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    try:
        symbol     = parts[1]
        action     = parts[2]
        entry      = float(parts[3])
        sl         = float(parts[4])
        tp         = float(parts[5])
        confidence = float(parts[6])
    except (IndexError, ValueError):
        await query.edit_message_text("⚠️ Could not parse signal data.", reply_markup=back_keyboard())
        return

    signal = Signal(
        symbol=symbol,
        direction=action,
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=confidence,
    )

    # Q Validation (QA)
    validation = validate_signal(signal)
    if not validation.valid:
        await query.edit_message_text(
            f"❌ Qubit Analytics (QA) — Signal Rejected\n\nReason: {validation.reason}",
            reply_markup=back_keyboard(),
        )
        return

    # Qubit Risk (QR)
    bal = get_balance()
    risk = check_risk(get_approved_count_today(), get_consecutive_losses(), bal)
    if not risk.allowed:
        await query.edit_message_text(
            f"❌ Qubit Risk (QR) — Trade Blocked\n\nReason: {risk.reason}",
            reply_markup=back_keyboard(),
        )
        return

    rr = calculate_rr(signal)
    signal_id = insert_trade(
        symbol=signal.symbol,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        confidence=signal.confidence,
        status="approved",
        reason="Auto-scan — Qubit Analytics (QA) ✅ | Qubit Risk (QR) ✅",
        risk_amount=risk.risk_amount,
        rr_ratio=rr,
    )
    pt_id = open_trade(
        signal_id=signal_id,
        symbol=signal.symbol,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        risk_amount=risk.risk_amount,
        rr_ratio=rr,
    )

    await query.edit_message_text(
        f"✅ Paper Trade Opened — #{pt_id}\n"
        f"{'━' * 28}\n"
        f"Symbol:      {signal.symbol}\n"
        f"Direction:   {signal.direction}\n"
        f"Entry:       {signal.entry}\n"
        f"SL:          {signal.stop_loss}\n"
        f"TP:          {signal.take_profit}\n"
        f"Confidence:  {signal.confidence:.0f}%\n"
        f"{'━' * 28}\n"
        f"Balance:     ${bal:,.2f}\n"
        f"Risk Amount: ${risk.risk_amount:,.2f}\n"
        f"R:R Ratio:   1:{rr}\n"
        f"Mode:        Paper Trading",
        reply_markup=back_keyboard(),
    )


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue task — runs every 10 min, posts signals to registered chats."""
    if not is_api_configured():
        return
    if get_setting("autoscan_enabled", "0") != "1":
        return
    chat_ids = get_alert_chats()
    if not chat_ids:
        return

    import asyncio
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, scan_markets)
    except Exception as exc:
        logger.warning("Auto-scan failed: %s", exc)
        return

    signals = [(sym, sig) for sym, sig in results if isinstance(sig, MarketSignal)]
    if not signals:
        return  # nothing actionable — stay silent

    for chat_id in chat_ids:
        for _, sig in signals:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=format_signal_message(sig, auto=True),
                    reply_markup=logsig_keyboard(sig),
                )
            except Exception as exc:
                logger.warning("Auto-scan send failed (chat %s): %s", chat_id, exc)


# ── App entry ──────────────────────────────────────────────────────────────────

def main() -> None:
    # Fix for Python 3.14+ — no default event loop
    if sys.version_info >= (3, 14):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

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
    app.add_handler(CommandHandler("mt5",          cmd_mt5))
    app.add_handler(CommandHandler("mt5account",   cmd_mt5account))
    app.add_handler(CommandHandler("mt5positions", cmd_mt5positions))
    app.add_handler(CommandHandler("scan",          cmd_scan))
    app.add_handler(CommandHandler("scanner",       cmd_scan))       # alias
    app.add_handler(CommandHandler("markets",       cmd_markets))
    app.add_handler(CommandHandler("watchlist",     cmd_watchlist))
    app.add_handler(CommandHandler("analyze",       cmd_analyze))
    app.add_handler(CommandHandler("setchat",       cmd_setchat))
    app.add_handler(CommandHandler("autoscan",      cmd_autoscan))
    app.add_handler(CommandHandler("chart",         cmd_chart))

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
    app.add_handler(CallbackQueryHandler(handle_close_trade,    pattern=r"^close_\d+_(win|loss|breakeven)$"))
    app.add_handler(CallbackQueryHandler(show_markets_btn,      pattern="^markets$"))
    app.add_handler(CallbackQueryHandler(show_watchlist_btn,    pattern="^watchlist$"))
    app.add_handler(CallbackQueryHandler(do_wl_reset,           pattern="^wl_reset$"))
    app.add_handler(CallbackQueryHandler(show_scan_btn,         pattern="^(market_scan|scanner)$"))
    app.add_handler(CallbackQueryHandler(handle_log_autosignal, pattern="^logsig_"))
    app.add_handler(CallbackQueryHandler(show_chart_btn,        pattern="^equity_chart$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))

    # Auto-scan job — every 10 minutes, first run after 60 s
    if app.job_queue is not None:
        app.job_queue.run_repeating(auto_scan_job, interval=600, first=60)
    else:
        logger.warning("JobQueue unavailable — install apscheduler>=3.6.3,<3.11 to enable auto-scan")

    logger.info("Qubit v3.0 — Live Market Data + Auto-Scan active")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
