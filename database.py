import sqlite3, os, logging
from collections import Counter
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "market.db")
RESERVE_MINUTES = 30


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    c = db()
    cur = c.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            username       TEXT UNIQUE NOT NULL COLLATE NOCASE,
            price          INTEGER NOT NULL,
            category       TEXT NOT NULL,
            length         INTEGER NOT NULL,
            readability    INTEGER NOT NULL,
            uniqueness     INTEGER NOT NULL,
            description    TEXT,
            is_sold        INTEGER DEFAULT 0,
            is_reserved    INTEGER DEFAULT 0,
            reserved_by    INTEGER,
            reserved_until TEXT,
            added_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            sold_at        TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id   INTEGER NOT NULL,
            username   TEXT NOT NULL,
            stars_paid INTEGER NOT NULL,
            status     TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            total_spent INTEGER DEFAULT 0
        )
    """)

    # Вотчлист: пользователь ждёт появления конкретного ника
    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            username TEXT NOT NULL COLLATE NOCASE,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, username)
        )
    """)

    c.commit()
    c.close()
    logger.info("DB ready")


# ── Обогащение данных ────────────────────────

def _enrich(row: dict) -> dict:
    u = row["username"]
    row["has_digits"] = int(any(c.isdigit() for c in u))
    letters = [c for c in u if c.isalpha()]
    cnt = Counter(letters)
    row["repeat_count"] = sum(1 for n in cnt.values() if n > 1)
    return row


# ── Каталог ──────────────────────────────────

def add_username(username, price, category, readability, uniqueness, description=""):
    c = db()
    cur = c.cursor()
    try:
        cur.execute("""
            INSERT INTO usernames
                (username, price, category, length, readability, uniqueness, description)
            VALUES (?,?,?,?,?,?,?)
        """, (username.lower(), price, category, len(username), readability, uniqueness, description))
        c.commit()
        added = True
    except sqlite3.IntegrityError:
        added = False
    finally:
        c.close()
    return added


def mark_sold(username: str, buyer_id: int, stars: int):
    c = db()
    cur = c.cursor()
    cur.execute("""
        UPDATE usernames SET is_sold=1, sold_at=?, is_reserved=0,
        reserved_by=NULL, reserved_until=NULL
        WHERE username=?
    """, (datetime.now().isoformat(), username.lower()))
    cur.execute("""
        INSERT INTO purchases (buyer_id, username, stars_paid, status)
        VALUES (?,?,?,'complete')
    """, (buyer_id, username.lower(), stars))
    cur.execute("""
        UPDATE users SET total_spent = total_spent + ? WHERE telegram_id = ?
    """, (stars, buyer_id))
    c.commit()
    c.close()


def get_catalog(category=None, sort="price_desc", max_price=None,
                max_length=None, search=None):
    c = db()
    cur = c.cursor()
    q = "SELECT * FROM usernames WHERE is_sold = 0"
    p = []

    if category and category != "Все":
        q += " AND category=?"; p.append(category)
    if max_price:
        q += " AND price<=?"; p.append(max_price)
    if max_length:
        q += " AND length<=?"; p.append(max_length)
    if search:
        q += " AND username LIKE ?"; p.append(f"%{search.lower()}%")

    order = {"price_desc": "price DESC", "price_asc": "price ASC",
             "length": "length ASC", "readability": "readability DESC",
             "newest": "added_at DESC"}.get(sort, "price DESC")
    q += f" ORDER BY {order}"

    cur.execute(q, p)
    rows = [_enrich(dict(r)) for r in cur.fetchall()]
    c.close()
    return rows


def get_username(username: str):
    c = db()
    cur = c.cursor()
    cur.execute("SELECT * FROM usernames WHERE username=?", (username.lower(),))
    row = cur.fetchone()
    c.close()
    return _enrich(dict(row)) if row else None


def get_stats():
    c = db()
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) t, MIN(price) mn, MAX(price) mx FROM usernames WHERE is_sold=0")
    r = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) s FROM usernames WHERE is_sold=1")
    r["sold"] = cur.fetchone()["s"]
    c.close()
    return r


def get_user_purchases(user_id: int):
    c = db()
    cur = c.cursor()
    cur.execute("""
        SELECT username, stars_paid, created_at FROM purchases
        WHERE buyer_id=? ORDER BY created_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    c.close()
    return rows


def upsert_user(telegram_id, username, first_name):
    c = db()
    cur = c.cursor()
    cur.execute("""
        INSERT INTO users (telegram_id, username, first_name)
        VALUES (?,?,?)
        ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (telegram_id, username, first_name))
    c.commit()
    c.close()


# ── Резервирование ───────────────────────────

def reserve(username: str, user_id: int) -> dict:
    c = db()
    cur = c.cursor()
    cur.execute("SELECT * FROM usernames WHERE username=?", (username.lower(),))
    row = cur.fetchone()

    if not row:
        c.close(); return {"ok": False, "reason": "not_found"}
    if row["is_sold"]:
        c.close(); return {"ok": False, "reason": "sold"}

    now = datetime.now()
    if row["is_reserved"] and row["reserved_by"] != user_id:
        until = datetime.fromisoformat(row["reserved_until"])
        if until > now:
            mins = int((until - now).total_seconds() / 60) + 1
            c.close(); return {"ok": False, "reason": "reserved", "minutes": mins}

    until = now + timedelta(minutes=RESERVE_MINUTES)
    cur.execute("""
        UPDATE usernames SET is_reserved=1, reserved_by=?, reserved_until=?
        WHERE username=?
    """, (user_id, until.isoformat(), username.lower()))
    c.commit(); c.close()
    return {"ok": True, "until": until.strftime("%H:%M"), "minutes": RESERVE_MINUTES}


def remove_username(username: str):
    """Удаляет ник из каталога (занят или появился на Fragment)."""
    c = db()
    c.execute("DELETE FROM usernames WHERE username=? AND is_sold=0", (username.lower(),))
    c.commit()
    c.close()


def release_expired():
    c = db()
    cur = c.cursor()
    cur.execute("""
        UPDATE usernames SET is_reserved=0, reserved_by=NULL, reserved_until=NULL
        WHERE is_reserved=1 AND reserved_until < ?
    """, (datetime.now().isoformat(),))
    n = cur.rowcount
    c.commit(); c.close()
    return n


def check_reservation(username: str, user_id: int) -> dict:
    c = db()
    cur = c.cursor()
    cur.execute("SELECT * FROM usernames WHERE username=?", (username.lower(),))
    row = cur.fetchone()
    c.close()
    if not row: return {"available": False, "reason": "not_found"}
    if row["is_sold"]: return {"available": False, "reason": "sold"}
    if row["is_reserved"]:
        until = datetime.fromisoformat(row["reserved_until"])
        if until > datetime.now():
            mine = row["reserved_by"] == user_id
            return {"available": mine, "reason": "mine" if mine else "taken",
                    "until": until.strftime("%H:%M")}
    return {"available": True, "reason": "free"}


# ── Вотчлист ─────────────────────────────────

def watch_add(user_id: int, username: str) -> bool:
    c = db()
    cur = c.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO watchlist (user_id, username) VALUES (?,?)",
                    (user_id, username.lower()))
        c.commit()
        ok = cur.rowcount > 0
    except Exception:
        ok = False
    finally:
        c.close()
    return ok


def watch_remove(user_id: int, username: str):
    c = db()
    c.execute("DELETE FROM watchlist WHERE user_id=? AND username=?",
              (user_id, username.lower()))
    c.commit(); c.close()


def watch_list(user_id: int):
    c = db()
    cur = c.cursor()
    cur.execute("""
        SELECT w.username,
               CASE WHEN u.id IS NOT NULL AND u.is_sold=0 THEN 1 ELSE 0 END as in_catalog,
               u.price
        FROM watchlist w
        LEFT JOIN usernames u ON w.username=u.username
        WHERE w.user_id=?
        ORDER BY w.added_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    c.close()
    return rows


def watch_get_subscribers(username: str) -> list[int]:
    """Все user_id кто подписан на этот ник."""
    c = db()
    cur = c.cursor()
    cur.execute("SELECT user_id FROM watchlist WHERE username=?", (username.lower(),))
    ids = [r["user_id"] for r in cur.fetchall()]
    c.close()
    return ids


def notify_watchlist(username: str) -> list[int]:
    """Возвращает список user_id которых надо уведомить о появлении ника."""
    return watch_get_subscribers(username)
