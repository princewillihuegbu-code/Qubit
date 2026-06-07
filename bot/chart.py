"""
Qubit — Equity Curve Chart Generator
Produces a PNG (BytesIO) showing balance growth + per-trade PnL bars.
Uses the Agg backend so no display is needed.
"""
from __future__ import annotations

import io
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
import matplotlib.ticker as mticker

from database import get_all_paper_trades, get_performance_stats
from paper_engine import get_balance

# ── Palette ────────────────────────────────────────────────────────────────────
BG       = "#0f1117"
PANEL    = "#1a1d27"
GREEN    = "#26a69a"
RED      = "#ef5350"
ACCENT   = "#5c6bc0"
TEXT     = "#e0e0e0"
SUBTEXT  = "#9e9e9e"
GRID     = "#2a2d3a"
LINE_COL = "#7986cb"


def _calc_max_drawdown(equity: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a negative dollar amount."""
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity[1:]:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def generate_equity_chart() -> io.BytesIO | None:
    """
    Build the equity curve chart from all closed paper trades.
    Returns a PNG BytesIO or None if there are no closed trades.
    """
    trades = get_all_paper_trades()
    closed = sorted(
        [t for t in trades if t["status"] == "closed" and t.get("pnl") is not None],
        key=lambda t: (t.get("close_date") or "", t.get("id", 0)),
    )

    if not closed:
        return None

    stats      = get_performance_stats()
    current_bal = get_balance()
    total_pnl  = sum(t["pnl"] for t in closed)
    start_bal  = current_bal - total_pnl

    # Build series
    pnls:   list[float] = [t["pnl"] for t in closed]
    labels: list[str]   = [t.get("symbol", "?") for t in closed]
    equity: list[float] = [start_bal]
    running = start_bal
    for p in pnls:
        running += p
        equity.append(running)

    n       = len(pnls)
    x_trades = list(range(1, n + 1))          # 1-indexed trade numbers
    x_equity = list(range(0, n + 1))          # includes start point (trade 0)

    max_dd = _calc_max_drawdown(equity)
    win_rate = stats["win_rate"]
    wins     = stats["wins"]
    losses   = stats["losses"]
    pf_str   = (f"{stats['profit_factor']:.2f}x"
                if stats["profit_factor"] != float("inf") else "∞")

    # ── Figure layout ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(10, 7), facecolor=BG)
    gs  = gridspec.GridSpec(
        2, 1,
        height_ratios=[3, 1.6],
        hspace=0.08,
        left=0.09, right=0.97,
        top=0.88, bottom=0.10,
    )

    ax_eq  = fig.add_subplot(gs[0])   # equity curve
    ax_pnl = fig.add_subplot(gs[1])   # per-trade bars

    for ax in (ax_eq, ax_pnl):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=SUBTEXT, labelsize=8)
        ax.spines[:].set_color(GRID)
        ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
        ax.grid(axis="x", color=GRID, linewidth=0.3, alpha=0.4)

    # ── Top: equity curve ─────────────────────────────────────────────────────
    ax_eq.plot(
        x_equity, equity,
        color=LINE_COL, linewidth=2.2, zorder=3,
        solid_capstyle="round",
    )
    ax_eq.fill_between(
        x_equity, equity, start_bal,
        where=[e >= start_bal for e in equity],
        color=GREEN, alpha=0.12, zorder=2,
    )
    ax_eq.fill_between(
        x_equity, equity, start_bal,
        where=[e < start_bal for e in equity],
        color=RED, alpha=0.12, zorder=2,
    )

    # Horizontal start line
    ax_eq.axhline(start_bal, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.5)

    # Mark final balance
    final_color = GREEN if equity[-1] >= start_bal else RED
    ax_eq.scatter([n], [equity[-1]], color=final_color, s=60, zorder=5)

    ax_eq.set_ylabel("Account Balance ($)", color=TEXT, fontsize=9, labelpad=8)
    ax_eq.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax_eq.set_xlim(-0.5, n + 0.5)
    ax_eq.tick_params(labelbottom=False)

    # ── Bottom: per-trade PnL bars ────────────────────────────────────────────
    bar_colors = [GREEN if p >= 0 else RED for p in pnls]
    ax_pnl.bar(x_trades, pnls, color=bar_colors, width=0.6, zorder=3, alpha=0.85)
    ax_pnl.axhline(0, color=SUBTEXT, linewidth=0.8)

    ax_pnl.set_xlabel("Trade #", color=TEXT, fontsize=9, labelpad=6)
    ax_pnl.set_ylabel("PnL ($)", color=TEXT, fontsize=9, labelpad=8)
    ax_pnl.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax_pnl.set_xlim(-0.5, n + 0.5)

    if n <= 20:
        ax_pnl.set_xticks(x_trades)
        ax_pnl.set_xticklabels(
            [f"{i}\n{lbl[:3]}" for i, lbl in zip(x_trades, labels)],
            fontsize=7, color=SUBTEXT,
        )
    else:
        ax_pnl.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))

    # ── Title & stats strip ───────────────────────────────────────────────────
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_pct  = (total_pnl / start_bal * 100) if start_bal else 0

    fig.text(
        0.09, 0.94,
        "Qubit — Equity Curve",
        color=TEXT, fontsize=13, fontweight="bold", va="bottom",
    )
    fig.text(
        0.09, 0.905,
        f"Balance: ${current_bal:,.2f}   |   "
        f"Total PnL: {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{pnl_pct:.1f}%)   |   "
        f"Trades: {n}   |   Win Rate: {win_rate:.1f}%   |   "
        f"W/L: {wins}/{losses}   |   Profit Factor: {pf_str}   |   "
        f"Max Drawdown: ${max_dd:,.2f}",
        color=SUBTEXT, fontsize=7.5, va="bottom",
    )

    # ── Render to BytesIO ─────────────────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
