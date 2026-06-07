import sqlite3
from datetime import date
from pathlib import Path

DB_FILE = Path(__file__).parent / "qai.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                direction   TEXT    NOT NULL,
                entry       REAL    NOT NULL,
                stop_loss   REAL    NOT NULL,
                take_profit REAL    NOT NULL,
                confidence  REAL    NOT NULL,
                status      TEXT    NOT NULL,
                reason      TEXT,
                risk_amount REAL,
                rr_ratio    REAL,
                timestamp   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id      INTEGER REFERENCES trades(id),
                symbol         TEXT    NOT NULL,
                direction      TEXT    NOT NULL,
                entry          REAL    NOT NULL,
                stop_loss      REAL    NOT NULL,
                take_profit    REAL    NOT NULL,
                risk_amount    REAL    NOT NULL,
                rr_ratio       REAL    NOT NULL,
                open_time      TEXT    NOT NULL DEFAULT (datetime('now')),
                open_date      TEXT    NOT NULL,
                close_time     TEXT,
                status         TEXT    NOT NULL DEFAULT 'open',
                result         TEXT,
                pnl            REAL,
                duration_min   INTEGER,
                balance_before REAL    NOT NULL,
                balance_after  REAL
            )
        """)


# ── Signal trades ──────────────────────────────────────────────────────────────

def insert_trade(
    symbol: str, direction: str, entry: float, stop_loss: float,
    take_profit: float, confidence: float, status: str, reason: str,
    risk_amount: float | None, rr_ratio: float | None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (date,symbol,direction,entry,stop_loss,take_profit,
                confidence,status,reason,risk_amount,rr_ratio)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(date.today()), symbol, direction, entry, stop_loss,
             take_profit, confidence, status, reason, risk_amount, rr_ratio),
        )
        return cur.lastrowid


def get_trades_by_status(status: str, day: str | None = None) -> list[sqlite3.Row]:
    day = day or str(date.today())
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM trades WHERE status=? AND date=? ORDER BY id DESC",
            (status, day),
        ).fetchall()


def get_approved_count_today() -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status='approved' AND date=?",
            (str(date.today()),),
        ).fetchone()[0]


def get_consecutive_losses() -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status FROM trades ORDER BY id DESC LIMIT 10"
        ).fetchall()
    count = 0
    for row in rows:
        if row["status"] == "rejected":
            count += 1
        else:
            break
    return count


def get_stats_today() -> dict:
    day = str(date.today())
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM trades WHERE date=? GROUP BY status",
            (day,),
        ).fetchall()
    stats = {"approved": 0, "rejected": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
    stats["total"] = stats["approved"] + stats["rejected"]
    return stats


def get_all_time_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM trades GROUP BY status"
        ).fetchall()
    stats = {"approved": 0, "rejected": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
    stats["total"] = stats["approved"] + stats["rejected"]
    return stats


# ── Settings ───────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ── Market filters (stored in settings) ───────────────────────────────────────

FILTER_KEYS = {
    "trend":      "filter_trend_flat",
    "volatility": "filter_volatility",
    "news":       "filter_news_risk",
}


def get_market_filters() -> dict[str, bool]:
    return {k: get_setting(v, "0") == "1" for k, v in FILTER_KEYS.items()}


def toggle_market_filter(key: str) -> bool:
    setting_key = FILTER_KEYS[key]
    current = get_setting(setting_key, "0") == "1"
    set_setting(setting_key, "0" if current else "1")
    return not current


def check_market_filters() -> tuple[bool, str]:
    filters = get_market_filters()
    if filters["trend"]:
        return True, "Market filter active: Trend is currently FLAT — no new trades"
    if filters["volatility"]:
        return True, "Market filter active: Volatility is HIGH — no new trades"
    if filters["news"]:
        return True, "Market filter active: News Risk flag is ON — no new trades"
    return False, ""


# ── Paper trades ───────────────────────────────────────────────────────────────

def create_paper_trade(
    signal_id: int, symbol: str, direction: str, entry: float,
    stop_loss: float, take_profit: float, risk_amount: float,
    rr_ratio: float, balance_before: float,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO paper_trades
               (signal_id,symbol,direction,entry,stop_loss,take_profit,
                risk_amount,rr_ratio,open_date,balance_before)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (signal_id, symbol, direction, entry, stop_loss, take_profit,
             risk_amount, rr_ratio, str(date.today()), balance_before),
        )
        return cur.lastrowid


def close_paper_trade(
    pt_id: int, result: str, pnl: float,
    balance_after: float, duration_min: int,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE paper_trades SET
               status='closed', result=?, pnl=?, balance_after=?,
               duration_min=?, close_time=datetime('now')
               WHERE id=?""",
            (result, pnl, balance_after, duration_min, pt_id),
        )


def get_open_paper_trades() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM paper_trades WHERE status='open' ORDER BY id DESC"
        ).fetchall()


def get_paper_trade_by_id(pt_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM paper_trades WHERE id=?", (pt_id,)
        ).fetchone()


def get_paper_trades_today() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM paper_trades WHERE open_date=? ORDER BY id DESC",
            (str(date.today()),),
        ).fetchall()


def get_all_paper_trades() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM paper_trades ORDER BY id DESC"
        ).fetchall()


def get_performance_stats() -> dict:
    with get_conn() as conn:
        closed = conn.execute(
            "SELECT * FROM paper_trades WHERE status='closed'"
        ).fetchall()
        open_count = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE status='open'"
        ).fetchone()[0]

    wins = [t for t in closed if t["result"] == "win"]
    losses = [t for t in closed if t["result"] == "loss"]
    breakevens = [t for t in closed if t["result"] == "breakeven"]

    gross_wins = sum(t["pnl"] for t in wins)
    gross_losses = abs(sum(t["pnl"] for t in losses))
    total_pnl = sum(t["pnl"] for t in closed)
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else float("inf")
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
    avg_win = round(gross_wins / len(wins), 2) if wins else 0.0
    avg_loss = round(gross_losses / len(losses), 2) if losses else 0.0

    best = max(closed, key=lambda t: t["pnl"], default=None)
    worst = min(closed, key=lambda t: t["pnl"], default=None)

    return {
        "open": open_count,
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "total_pnl": round(total_pnl, 2),
        "gross_wins": round(gross_wins, 2),
        "gross_losses": round(gross_losses, 2),
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": best,
        "worst_trade": worst,
    }


# ── Alert chat IDs (for auto-scan broadcasts) ─────────────────────────────────

def add_alert_chat(chat_id: int) -> None:
    current = get_setting("alert_chat_ids", "")
    ids = [x for x in current.split(",") if x]
    if str(chat_id) not in ids:
        ids.append(str(chat_id))
    set_setting("alert_chat_ids", ",".join(ids))


def remove_alert_chat(chat_id: int) -> None:
    current = get_setting("alert_chat_ids", "")
    ids = [x for x in current.split(",") if x and x != str(chat_id)]
    set_setting("alert_chat_ids", ",".join(ids))


def get_alert_chats() -> list[int]:
    current = get_setting("alert_chat_ids", "")
    return [int(x) for x in current.split(",") if x]


def get_daily_pnl_today() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(pnl) FROM paper_trades WHERE status='closed' AND open_date=?",
            (str(date.today()),),
        ).fetchone()
        return row[0] or 0.0
