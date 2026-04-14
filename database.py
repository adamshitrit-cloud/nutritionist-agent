"""
database.py — Postgres (Neon) data layer for NutriAI.

Drop-in replacement for all Redis raw operations.
Falls back to Redis when DATABASE_URL is not set.

Schema (auto-created on first run):
  users               — user accounts
  user_data           — JSONB blobs: progress, user_profile, agent_memory, meal_plan
  conversation_history— per-user chat history
  message_counts      — monthly free-tier message caps
  stripe_data         — stripe subscription status
  referrals           — referral codes + counts
  water_logs          — daily water intake
  shields             — streak shield usage
  viral_notifications — streak milestone de-dup
  kv                  — generic key-value for everything else
"""

import json
import os
import threading
from typing import Optional, Any

# ── Connection pool (lazy, thread-safe) ──────────────────────────────────────
_pool = None
_pool_lock = threading.Lock()

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        if not DATABASE_URL:
            return None
        try:
            from psycopg2 import pool as pg_pool
            _pool = pg_pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL,
                connect_timeout=5,
            )
            print("[DB] Postgres connection pool created")
            _ensure_schema()
        except Exception as e:
            print(f"[DB] Failed to create pool: {e}")
            _pool = None
        return _pool


def _conn():
    """Get a connection from the pool. Caller MUST call pool.putconn(conn) or use as context."""
    p = _get_pool()
    if p is None:
        raise RuntimeError("No database pool available")
    return p.getconn()


def _put(conn):
    p = _get_pool()
    if p:
        p.putconn(conn)


def _exec(sql: str, params=None, fetch: str = None):
    """
    Execute a SQL statement.
    fetch: None | 'one' | 'all'
    Returns fetched rows or None.
    """
    conn = None
    try:
        conn = _conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
    finally:
        if conn is not None:
            _put(conn)


def is_available() -> bool:
    """True if Postgres is configured and reachable."""
    return _get_pool() is not None


# ── Schema bootstrap ─────────────────────────────────────────────────────────

def _ensure_schema():
    conn = _conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL DEFAULT '',
                    email        TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL DEFAULT '',
                    salt         TEXT NOT NULL DEFAULT '',
                    lang         TEXT NOT NULL DEFAULT 'he',
                    phone        TEXT NOT NULL DEFAULT '',
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS users_email_idx ON users(email);
                CREATE INDEX IF NOT EXISTS users_phone_idx ON users(phone) WHERE phone <> '';

                CREATE TABLE IF NOT EXISTS user_data (
                    user_id      TEXT NOT NULL,
                    key          TEXT NOT NULL,
                    value        JSONB NOT NULL DEFAULT '{}',
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS conversation_history (
                    user_id      TEXT PRIMARY KEY,
                    messages     JSONB NOT NULL DEFAULT '[]',
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS message_counts (
                    user_id      TEXT NOT NULL,
                    month        TEXT NOT NULL,
                    count        INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, month)
                );

                CREATE TABLE IF NOT EXISTS stripe_data (
                    user_id      TEXT PRIMARY KEY,
                    status       TEXT NOT NULL DEFAULT '',
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    user_id      TEXT PRIMARY KEY,
                    code         TEXT UNIQUE NOT NULL,
                    count        INTEGER NOT NULL DEFAULT 0,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS referrals_code_idx ON referrals(code);

                CREATE TABLE IF NOT EXISTS water_logs (
                    user_id      TEXT NOT NULL,
                    date         TEXT NOT NULL,
                    glasses      INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, date)
                );

                CREATE TABLE IF NOT EXISTS shields (
                    user_id      TEXT NOT NULL,
                    month        TEXT NOT NULL,
                    dates        JSONB NOT NULL DEFAULT '[]',
                    shield_used  BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (user_id, month)
                );

                CREATE TABLE IF NOT EXISTS viral_notifications (
                    user_id      TEXT NOT NULL,
                    streak       INTEGER NOT NULL,
                    sent_date    TEXT NOT NULL,
                    PRIMARY KEY (user_id, streak)
                );

                CREATE TABLE IF NOT EXISTS kv (
                    key          TEXT PRIMARY KEY,
                    value        TEXT NOT NULL DEFAULT '',
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """)
        print("[DB] Schema verified")
    finally:
        _put(conn)


# ── User accounts ─────────────────────────────────────────────────────────────

def db_get_user_by_email(email: str) -> Optional[dict]:
    """Returns user dict or None."""
    try:
        row = _exec(
            "SELECT id, name, email, password_hash, salt, lang, phone, created_at "
            "FROM users WHERE email = %s",
            (email.lower(),), fetch="one"
        )
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "email": row[2],
            "password_hash": row[3], "salt": row[4], "lang": row[5],
            "phone": row[6], "created_at": str(row[7])
        }
    except Exception as e:
        print(f"[DB] get_user_by_email error: {e}")
        return None


def db_save_user(user: dict):
    """Upsert user record."""
    try:
        # Handle created_at: if "NOW()" literal or missing, use SQL NOW(); otherwise pass as parameter
        created = user.get("created_at")
        if not created or created == "NOW()":
            _exec("""
                INSERT INTO users (id, name, email, password_hash, salt, lang, phone, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
                ON CONFLICT (email) DO UPDATE SET
                    name=EXCLUDED.name, password_hash=EXCLUDED.password_hash,
                    salt=EXCLUDED.salt, lang=EXCLUDED.lang, phone=EXCLUDED.phone
            """, (
                user["id"], user.get("name",""), user["email"].lower(),
                user.get("password_hash",""), user.get("salt",""),
                user.get("lang","he"), user.get("phone",""),
            ))
        else:
            _exec("""
                INSERT INTO users (id, name, email, password_hash, salt, lang, phone, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (email) DO UPDATE SET
                    name=EXCLUDED.name, password_hash=EXCLUDED.password_hash,
                    salt=EXCLUDED.salt, lang=EXCLUDED.lang, phone=EXCLUDED.phone
            """, (
                user["id"], user.get("name",""), user["email"].lower(),
                user.get("password_hash",""), user.get("salt",""),
                user.get("lang","he"), user.get("phone",""),
                created
            ))
    except Exception as e:
        print(f"[DB] save_user error: {e}")


def db_get_user_id_by_phone(phone_digits: str) -> Optional[str]:
    """Look up user_id by phone digits."""
    try:
        row = _exec("SELECT id FROM users WHERE phone = %s", (phone_digits,), fetch="one")
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] get_user_id_by_phone error: {e}")
        return None


def db_link_phone(phone_digits: str, user_id: str):
    """Set phone on the user record."""
    try:
        _exec("UPDATE users SET phone = %s WHERE id = %s", (phone_digits, user_id))
    except Exception as e:
        print(f"[DB] link_phone error: {e}")


def db_all_users_with_phones() -> list:
    """Return all users that have a phone number (for weekly summary)."""
    try:
        rows = _exec(
            "SELECT id, name, phone FROM users WHERE phone <> '' AND phone IS NOT NULL",
            fetch="all"
        )
        return [{"id": r[0], "name": r[1], "phone": r[2]} for r in (rows or [])]
    except Exception as e:
        print(f"[DB] all_users_with_phones error: {e}")
        return []


# ── JSONB user data blobs ────────────────────────────────────────────────────

def db_get_json(user_id: str, key: str) -> dict:
    """
    Get a JSONB blob (progress, user_profile, agent_memory, meal_plan).
    Key is the file stem: 'progress', 'user_profile', 'agent_memory', 'meal_plan'.
    """
    try:
        row = _exec(
            "SELECT value FROM user_data WHERE user_id = %s AND key = %s",
            (user_id, key), fetch="one"
        )
        return row[0] if row else {}
    except Exception as e:
        print(f"[DB] get_json({user_id},{key}) error: {e}")
        return {}


def db_save_json(user_id: str, key: str, data: dict):
    """Upsert a JSONB blob."""
    try:
        _exec("""
            INSERT INTO user_data (user_id, key, value, updated_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (user_id, key, json.dumps(data, ensure_ascii=False)))
    except Exception as e:
        print(f"[DB] save_json({user_id},{key}) error: {e}")


# ── Conversation history ─────────────────────────────────────────────────────

def db_load_history(user_id: str) -> list:
    try:
        row = _exec(
            "SELECT messages FROM conversation_history WHERE user_id = %s",
            (user_id,), fetch="one"
        )
        return row[0] if row else []
    except Exception as e:
        print(f"[DB] load_history error: {e}")
        return []


def db_save_history(user_id: str, history: list):
    try:
        _exec("""
            INSERT INTO conversation_history (user_id, messages, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE SET messages=EXCLUDED.messages, updated_at=NOW()
        """, (user_id, json.dumps(history, ensure_ascii=False)))
    except Exception as e:
        print(f"[DB] save_history error: {e}")


# ── Message counts ───────────────────────────────────────────────────────────

def db_get_message_count(user_id: str, month: str) -> int:
    try:
        row = _exec(
            "SELECT count FROM message_counts WHERE user_id = %s AND month = %s",
            (user_id, month), fetch="one"
        )
        return row[0] if row else 0
    except Exception as e:
        print(f"[DB] get_message_count error: {e}")
        return 0


def db_increment_message_count(user_id: str, month: str) -> int:
    try:
        row = _exec("""
            INSERT INTO message_counts (user_id, month, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, month) DO UPDATE SET count = message_counts.count + 1
            RETURNING count
        """, (user_id, month), fetch="one")
        return row[0] if row else 1
    except Exception as e:
        print(f"[DB] increment_message_count error: {e}")
        return 0


# ── Stripe ───────────────────────────────────────────────────────────────────

def db_get_stripe_status(user_id: str) -> Optional[str]:
    try:
        row = _exec("SELECT status FROM stripe_data WHERE user_id = %s", (user_id,), fetch="one")
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] get_stripe_status error: {e}")
        return None


def db_set_stripe_status(user_id: str, status: str):
    try:
        _exec("""
            INSERT INTO stripe_data (user_id, status, updated_at) VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET status=EXCLUDED.status, updated_at=NOW()
        """, (user_id, status))
    except Exception as e:
        print(f"[DB] set_stripe_status error: {e}")


# ── Referrals ────────────────────────────────────────────────────────────────

def db_get_referral_count(user_id: str) -> int:
    try:
        row = _exec("SELECT count FROM referrals WHERE user_id = %s", (user_id,), fetch="one")
        return row[0] if row else 0
    except Exception as e:
        print(f"[DB] get_referral_count error: {e}")
        return 0


def db_get_referral_code(user_id: str) -> Optional[str]:
    try:
        row = _exec("SELECT code FROM referrals WHERE user_id = %s", (user_id,), fetch="one")
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] get_referral_code error: {e}")
        return None


def db_create_referral_code(user_id: str, code: str) -> str:
    """Create referral record; returns code (may differ if collision)."""
    try:
        _exec("""
            INSERT INTO referrals (user_id, code) VALUES (%s, %s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id, code))
        # Re-read in case of conflict
        row = _exec("SELECT code FROM referrals WHERE user_id = %s", (user_id,), fetch="one")
        return row[0] if row else code
    except Exception as e:
        print(f"[DB] create_referral_code error: {e}")
        return code


def db_get_user_id_by_code(code: str) -> Optional[str]:
    try:
        row = _exec("SELECT user_id FROM referrals WHERE code = %s", (code,), fetch="one")
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] get_user_id_by_code error: {e}")
        return None


def db_increment_referral_count(user_id: str) -> int:
    try:
        row = _exec("""
            UPDATE referrals SET count = count + 1 WHERE user_id = %s RETURNING count
        """, (user_id,), fetch="one")
        return row[0] if row else 0
    except Exception as e:
        print(f"[DB] increment_referral_count error: {e}")
        return 0


# ── Water ────────────────────────────────────────────────────────────────────

def db_get_water(user_id: str, date: str) -> int:
    try:
        row = _exec(
            "SELECT glasses FROM water_logs WHERE user_id = %s AND date = %s",
            (user_id, date), fetch="one"
        )
        return row[0] if row else 0
    except Exception as e:
        print(f"[DB] get_water error: {e}")
        return 0


def db_set_water(user_id: str, date: str, glasses: int):
    try:
        _exec("""
            INSERT INTO water_logs (user_id, date, glasses) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET glasses=EXCLUDED.glasses
        """, (user_id, date, glasses))
    except Exception as e:
        print(f"[DB] set_water error: {e}")


# ── Shields ──────────────────────────────────────────────────────────────────

def db_get_shields(user_id: str, month: str) -> dict:
    """Returns {'dates': [...], 'shield_used': bool}"""
    try:
        row = _exec(
            "SELECT dates, shield_used FROM shields WHERE user_id = %s AND month = %s",
            (user_id, month), fetch="one"
        )
        return {"dates": row[0] if row else [], "shield_used": row[1] if row else False}
    except Exception as e:
        print(f"[DB] get_shields error: {e}")
        return {"dates": [], "shield_used": False}


def db_set_shield(user_id: str, month: str, dates: list, shield_used: bool):
    try:
        _exec("""
            INSERT INTO shields (user_id, month, dates, shield_used)
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (user_id, month) DO UPDATE
            SET dates=EXCLUDED.dates, shield_used=EXCLUDED.shield_used
        """, (user_id, month, json.dumps(dates), shield_used))
    except Exception as e:
        print(f"[DB] set_shield error: {e}")


# ── Viral notifications ──────────────────────────────────────────────────────

def db_viral_already_sent(user_id: str, streak: int) -> bool:
    """True if this streak milestone was already sent."""
    try:
        row = _exec(
            "SELECT sent_date FROM viral_notifications WHERE user_id = %s AND streak = %s",
            (user_id, streak), fetch="one"
        )
        return row is not None
    except Exception as e:
        print(f"[DB] viral_already_sent error: {e}")
        return False


def db_mark_viral_sent(user_id: str, streak: int, date: str):
    try:
        _exec("""
            INSERT INTO viral_notifications (user_id, streak, sent_date)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, streak) DO UPDATE SET sent_date=EXCLUDED.sent_date
        """, (user_id, streak, date))
    except Exception as e:
        print(f"[DB] mark_viral_sent error: {e}")


# ── Generic KV (catch-all for edge cases) ────────────────────────────────────

def db_kv_get(key: str) -> Optional[str]:
    try:
        row = _exec("SELECT value FROM kv WHERE key = %s", (key,), fetch="one")
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] kv_get({key}) error: {e}")
        return None


def db_kv_set(key: str, value: str):
    try:
        _exec("""
            INSERT INTO kv (key, value, updated_at) VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (key, value))
    except Exception as e:
        print(f"[DB] kv_set({key}) error: {e}")


def db_kv_del(key: str):
    try:
        _exec("DELETE FROM kv WHERE key = %s", (key,))
    except Exception as e:
        print(f"[DB] kv_del({key}) error: {e}")
