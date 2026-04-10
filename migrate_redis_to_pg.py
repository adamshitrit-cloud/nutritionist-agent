"""
migrate_redis_to_pg.py — One-time migration from Upstash Redis → Neon Postgres.

Run ONCE after setting DATABASE_URL on the server (or locally with both env vars set):

    DATABASE_URL="postgresql://..." UPSTASH_REDIS_REST_URL="..." UPSTASH_REDIS_REST_TOKEN="..." python migrate_redis_to_pg.py

What it migrates:
  - account:{email}          → users table
  - phone:{digits}           → users.phone column
  - referral_code:{uid}      → referrals table
  - referral_count:{uid}     → referrals.count
  - {uid}:conversation_history → conversation_history table
  - msg_count:{uid}:{month}  → message_counts table
  - stripe_sub:{uid}         → stripe_data table
  - {uid}:water:{date}       → water_logs table
  - shields:{uid}:{month}    → shields table
  - streak_viral:{uid}:{n}   → viral_notifications table
  - {uid}:progress           → user_data (key=progress)
  - {uid}:user_profile       → user_data (key=user_profile)
  - {uid}:agent_memory       → user_data (key=agent_memory)
  - {uid}:meal_plan          → user_data (key=meal_plan)
"""

import json
import os
import sys
import urllib.request

# ── Redis helper ─────────────────────────────────────────────────────────────
REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

if not REDIS_URL or not REDIS_TOKEN:
    print("ERROR: UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set")
    sys.exit(1)

def redis_get(key: str):
    req = urllib.request.Request(
        f"{REDIS_URL}/get/{key}",
        headers={"Authorization": f"Bearer {REDIS_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get("result")

def redis_scan(pattern: str, count: int = 100):
    """Scan all keys matching pattern. Returns list of key strings."""
    cursor = 0
    all_keys = []
    while True:
        req = urllib.request.Request(
            f"{REDIS_URL}/scan/{cursor}/match/{pattern}/count/{count}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())["result"]
        cursor = int(result[0])
        all_keys.extend(result[1])
        if cursor == 0:
            break
    return all_keys

# ── DB module ────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL must be set")
    sys.exit(1)

import database as db

if not db.is_available():
    print("ERROR: Could not connect to Postgres. Check DATABASE_URL.")
    sys.exit(1)

print("✅ Postgres connected")

# ── Migrate users ─────────────────────────────────────────────────────────────
print("\n📦 Migrating users...")
account_keys = redis_scan("account:*")
print(f"  Found {len(account_keys)} accounts in Redis")
user_ids = []  # collect all user IDs for subsequent migrations

for key in account_keys:
    raw = redis_get(key)
    if not raw:
        continue
    try:
        user = json.loads(raw)
        db.db_save_user(user)
        uid = user.get("id")
        if uid:
            user_ids.append(uid)
        print(f"  ✓ {user.get('email','?')} ({uid})")
    except Exception as e:
        print(f"  ✗ {key}: {e}")

print(f"  Migrated {len(user_ids)} users")

# ── Migrate phone → uid mappings ─────────────────────────────────────────────
print("\n📱 Migrating phone mappings...")
phone_keys = redis_scan("phone:*")
for key in phone_keys:
    digits = key.replace("phone:", "")
    uid = redis_get(key)
    if uid:
        db.db_link_phone(digits, uid)
        print(f"  ✓ {digits} → {uid}")

# ── Migrate referrals ─────────────────────────────────────────────────────────
print("\n🔗 Migrating referrals...")
for uid in user_ids:
    code = redis_get(f"referral_code:{uid}")
    count_raw = redis_get(f"referral_count:{uid}")
    count = int(count_raw) if count_raw else 0
    if code:
        db.db_create_referral_code(uid, code)
        if count > 0:
            # Set count directly via kv fallback (db_create sets count=0)
            db._exec(
                "UPDATE referrals SET count = %s WHERE user_id = %s",
                (count, uid)
            )
        print(f"  ✓ {uid}: code={code}, count={count}")

# ── Migrate conversation history ──────────────────────────────────────────────
print("\n💬 Migrating conversation histories...")
for uid in user_ids:
    raw = redis_get(f"{uid}:conversation_history")
    if raw:
        try:
            history = json.loads(raw)
            db.db_save_history(uid, history)
            print(f"  ✓ {uid}: {len(history)} messages")
        except Exception as e:
            print(f"  ✗ {uid}: {e}")

# ── Migrate message counts ─────────────────────────────────────────────────────
print("\n📊 Migrating message counts...")
count_keys = redis_scan("msg_count:*")
for key in count_keys:
    # key format: msg_count:{uid}:{YYYY-MM}
    parts = key.split(":")
    if len(parts) == 3:
        _, uid, month = parts
        raw = redis_get(key)
        if raw:
            count = int(raw)
            db._exec("""
                INSERT INTO message_counts (user_id, month, count)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, month) DO UPDATE SET count=EXCLUDED.count
            """, (uid, month, count))
            print(f"  ✓ {uid} {month}: {count} messages")

# ── Migrate stripe data ────────────────────────────────────────────────────────
print("\n💳 Migrating stripe data...")
for uid in user_ids:
    status = redis_get(f"stripe_sub:{uid}")
    if status:
        db.db_set_stripe_status(uid, status)
        print(f"  ✓ {uid}: {status}")

# ── Migrate water logs ────────────────────────────────────────────────────────
print("\n💧 Migrating water logs...")
water_keys = redis_scan("*:water:*")
for key in water_keys:
    # key format: {uid}:water:{date}
    parts = key.split(":")
    if len(parts) == 3:
        uid, _, date = parts
        raw = redis_get(key)
        if raw:
            glasses = int(raw)
            db.db_set_water(uid, date, glasses)
            print(f"  ✓ {uid} {date}: {glasses} glasses")

# ── Migrate shields ────────────────────────────────────────────────────────────
print("\n🛡️ Migrating shields...")
shield_keys = redis_scan("shields:*")
for key in shield_keys:
    # key format: shields:{uid}:{month}
    parts = key.replace("shields:", "").split(":")
    if len(parts) == 2:
        uid, month = parts
        raw = redis_get(key)
        if raw:
            dates = json.loads(raw)
            used_raw = redis_get(f"shield_used:{uid}:{month}")
            used = bool(used_raw)
            db.db_set_shield(uid, month, dates, used)
            print(f"  ✓ {uid} {month}: dates={dates}, used={used}")

# ── Migrate viral notifications ───────────────────────────────────────────────
print("\n🔥 Migrating viral notifications...")
viral_keys = redis_scan("streak_viral:*")
for key in viral_keys:
    # key format: streak_viral:{uid}:{streak}
    parts = key.replace("streak_viral:", "").rsplit(":", 1)
    if len(parts) == 2:
        uid, streak_str = parts
        try:
            streak = int(streak_str)
            db.db_mark_viral_sent(uid, streak, "migrated")
            print(f"  ✓ {uid} streak={streak}")
        except Exception as e:
            print(f"  ✗ {key}: {e}")

# ── Migrate user JSONB blobs ──────────────────────────────────────────────────
print("\n🗂️ Migrating user data blobs...")
DATA_KEYS = ["progress", "user_profile", "agent_memory", "meal_plan"]
for uid in user_ids:
    for blob_key in DATA_KEYS:
        redis_key = f"{uid}:{blob_key}"
        raw = redis_get(redis_key)
        if raw:
            try:
                data = json.loads(raw)
                db.db_save_json(uid, blob_key, data)
                print(f"  ✓ {uid}:{blob_key}")
            except Exception as e:
                print(f"  ✗ {uid}:{blob_key}: {e}")

print("\n🎉 Migration complete!")
print(f"  Users: {len(user_ids)}")
