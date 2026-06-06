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


def insert_trade(
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    confidence: float,
    status: str,
    reason: str,
    risk_amount: float | None,
    rr_ratio: float | None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades
                (date, symbol, direction, entry, stop_loss, take_profit,
                 confidence, status, reason, risk_amount, rr_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(date.today()), symbol, direction, entry,
                stop_loss, take_profit, confidence,
                status, reason, risk_amount, rr_ratio,
            ),
        )
        return cur.lastrowid


def get_trades_by_status(status: str, day: str | None = None) -> list[sqlite3.Row]:
    day = day or str(date.today())
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM trades WHERE status = ? AND date = ? ORDER BY id DESC",
            (status, day),
        ).fetchall()


def get_approved_count_today() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status = 'approved' AND date = ?",
            (str(date.today()),),
        ).fetchone()
        return row[0]


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
            "SELECT status, COUNT(*) as cnt FROM trades WHERE date = ? GROUP BY status",
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
