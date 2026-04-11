"""
Flask web server for the Smart Nutritionist Agent — Multi-user edition.
Supports WhatsApp (Twilio) + web UI with per-user isolated Redis storage.
"""
from flask import (Flask, render_template, request, jsonify,
                   Response, session, redirect, url_for)
import anthropic
import json, os, sys, base64, re, hashlib, secrets, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Timezone helpers ──────────────────────────────────────────────────────────
# All date strings in Redis are stored by agent.py using UTC+2 (Israel / UK BST).
# Web UI must use the same offset so "today" always refers to the same calendar day.
_IL_TZ = timezone(timedelta(hours=2))   # Israel standard / UK BST

def _now_il() -> datetime:
    """Current datetime in Israel/IL timezone."""
    return datetime.now(_IL_TZ)

def _today() -> str:
    """Today's date string in IL timezone — matches agent.py's log dates."""
    return _now_il().strftime("%Y-%m-%d")

def _today_minus(days: int) -> str:
    return (_now_il() - timedelta(days=days)).strftime("%Y-%m-%d")

sys.path.insert(0, str(Path(__file__).parent))
import agent as nutritionist

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "conversation_history.json"

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",  # REST-based Upstash URL is not compatible with flask-limiter
)

client = None

# ── i18n ──────────────────────────────────────────────────────────────────────
from i18n import t as _t

@app.context_processor
def inject_t():
    lang = session.get("lang", "he")
    return {"t": lambda key, **kw: _t(key, lang, **kw), "lang": lang}

# ── PostHog analytics ─────────────────────────────────────────────────────────
def _track(event: str, uid: str = None, props: dict = None):
    """Fire a PostHog event non-blocking. Silently ignores if key not set."""
    ph_key = os.environ.get("POSTHOG_API_KEY")
    if not ph_key:
        return
    try:
        import threading
        def _send():
            import requests as _req
            _req.post(
                "https://app.posthog.com/capture/",
                json={
                    "api_key": ph_key,
                    "event": event,
                    "distinct_id": uid or "anonymous",
                    "properties": props or {},
                },
                timeout=3,
            )
        threading.Thread(target=_send, daemon=True).start()
    except Exception:
        pass

# ── DB import (lazy — only used when DATABASE_URL is set) ────────────────────
import database as _db_module

# ── Redis helpers ────────────────────────────────────────────────────────────

def _redis_raw_get(key: str):
    url   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    import urllib.request
    req = urllib.request.Request(f"{url}/get/{key}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read()).get("result")

def _redis_raw_set(key: str, value: str):
    url   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return
    import urllib.request
    body = json.dumps(["SET", key, value]).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()

def _redis_raw_del(key: str):
    url   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return
    import urllib.request
    body = json.dumps(["DEL", key]).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()

# ── Usage tracking ────────────────────────────────────────────────────────────
FREE_MONTHLY_CAP = 50  # messages per month for free users

def get_monthly_message_count(uid: str) -> int:
    """Return how many messages this user sent this calendar month."""
    month = datetime.now().strftime('%Y-%m')
    if _db_module.is_available():
        return _db_module.db_get_message_count(uid, month)
    key = f"msg_count:{uid}:{month}"
    val = _redis_raw_get(key)
    return int(val) if val else 0

def increment_monthly_message_count(uid: str) -> int:
    """Increment and return new count."""
    month = datetime.now().strftime('%Y-%m')
    if _db_module.is_available():
        return _db_module.db_increment_message_count(uid, month)
    key = f"msg_count:{uid}:{month}"
    val = _redis_raw_get(key)
    new_count = (int(val) if val else 0) + 1
    _redis_raw_set(key, str(new_count))
    return new_count

def is_paid_user(uid: str) -> bool:
    """True if user has active Stripe subscription OR earned premium via referrals."""
    if _db_module.is_available():
        stripe_status = _db_module.db_get_stripe_status(uid)
        if stripe_status == "active":
            return True
        referral_count = _db_module.db_get_referral_count(uid)
        return referral_count >= 3
    # Redis fallback
    stripe_status = _redis_raw_get(f"stripe_sub:{uid}")
    if stripe_status == "active":
        return True
    referral_count = _redis_raw_get(f"referral_count:{uid}")
    return int(referral_count or 0) >= 3

# ── User accounts (stored in Redis) ─────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def _get_user_by_email(email: str) -> dict:
    if _db_module.is_available():
        return _db_module.db_get_user_by_email(email)
    try:
        raw = _redis_raw_get(f"account:{email.lower()}")
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _save_user(user: dict):
    if _db_module.is_available():
        _db_module.db_save_user(user)
        return
    try:
        _redis_raw_set(f"account:{user['email'].lower()}", json.dumps(user, ensure_ascii=False))
    except Exception as e:
        print(f"[Auth] save_user error: {e}")

def _phone_digits(phone: str) -> str:
    """Strip all non-digits from a phone number. '05X-XXX' → '05XXXX', 'whatsapp:+972...' → '972...'"""
    return re.sub(r'\D', '', phone)

def _link_phone_to_user(phone: str, user_id: str):
    """Store phone→user_id mapping so WhatsApp messages find the right account."""
    digits = _phone_digits(phone)
    if not digits:
        return
    if _db_module.is_available():
        _db_module.db_link_phone(digits, user_id)
        return
    try:
        _redis_raw_set(f"phone:{digits}", user_id)
    except Exception as e:
        print(f"[Auth] link_phone error: {e}")

def _get_user_id_by_phone(phone: str) -> str | None:
    """Look up user_id from phone number digits. Returns None if not found."""
    digits = _phone_digits(phone)
    if not digits:
        return None
    if _db_module.is_available():
        return _db_module.db_get_user_id_by_phone(digits)
    try:
        return _redis_raw_get(f"phone:{digits}")
    except Exception:
        return None

def register_user(name: str, email: str, password: str, lang: str = "he", phone: str = "") -> dict:
    """Returns {'ok': True, 'user_id': ...} or {'error': '...'}"""
    email = email.lower().strip()
    if _get_user_by_email(email):
        return {"error": "כתובת המייל כבר רשומה" if lang == "he" else "Email already registered"}
    salt = secrets.token_hex(16)
    user = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "email": email,
        "password_hash": _hash_password(password, salt),
        "salt": salt,
        "lang": lang,
        "phone": _phone_digits(phone),
        "created_at": datetime.now().isoformat()
    }
    _save_user(user)
    if phone:
        _link_phone_to_user(phone, user["id"])
    _track("user_registered", user["id"], {"lang": lang, "has_phone": bool(phone)})
    return {"ok": True, "user_id": user["id"], "name": user["name"], "lang": lang}

def login_user(email: str, password: str) -> dict:
    """Returns {'ok': True, 'user_id': ...} or {'error': '...'}"""
    user = _get_user_by_email(email.lower().strip())
    if not user:
        return {"error": "המייל לא נמצא" }
    if _hash_password(password, user["salt"]) != user["password_hash"]:
        return {"error": "סיסמה שגויה"}
    _track("user_login", user["id"], {"lang": user.get("lang", "he")})
    return {"ok": True, "user_id": user["id"], "name": user["name"], "lang": user.get("lang", "he")}

# ── History helpers ──────────────────────────────────────────────────────────

def _clean_history(history: list) -> list:
    """Remove orphaned tool_result blocks that have no matching tool_use."""
    # Collect all tool_use ids
    tool_use_ids = set()
    for msg in history:
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_ids.add(block.get("id"))
                elif hasattr(block, "type") and block.type == "tool_use":
                    tool_use_ids.add(block.id)

    # Remove messages that are pure orphaned tool_results
    cleaned = []
    for msg in history:
        content = msg.get("content", [])
        if isinstance(content, list) and content and all(
            (isinstance(b, dict) and b.get("type") == "tool_result") for b in content
        ):
            # Only keep if all tool_use_ids are present
            if all(b.get("tool_use_id") in tool_use_ids for b in content):
                cleaned.append(msg)
        else:
            cleaned.append(msg)
    return cleaned

def _safe_truncate(history: list, max_len: int) -> list:
    """Truncate history to max_len messages, never splitting tool_use/tool_result pairs."""
    if len(history) <= max_len:
        return history
    history = history[-max_len:]
    # Drop orphaned tool_result messages at the start (at most 2 to prevent emptying entire history)
    pruned = 0
    while history and pruned < 2:
        first = history[0]
        content = first.get("content", [])
        if isinstance(content, list) and content and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            history = history[1:]
            pruned += 1
        else:
            break
    return _clean_history(history) if history else []

# ── Per-user conversation history ────────────────────────────────────────────

def _history_key(user_id: str) -> str:
    return f"{user_id}:conversation_history"

def load_history(user_id: str) -> list:
    # 1. Postgres
    if _db_module.is_available():
        result = _db_module.db_load_history(user_id)
        if result is not None:
            return result
    # 2. Redis
    try:
        raw = _redis_raw_get(_history_key(user_id))
        if raw is not None:
            return json.loads(raw) if raw else []
    except Exception as e:
        print(f"[Redis] load_history error: {e}")
    # 3. File
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_history(user_id: str, history: list):
    try:
        serializable = [
            {"role": m["role"], "content": _serialize_content(m["content"])}
            for m in history
        ]
        # 1. Postgres
        if _db_module.is_available():
            _db_module.db_save_history(user_id, serializable)
            return
        # 2. Redis
        try:
            _redis_raw_set(_history_key(user_id), json.dumps(serializable, ensure_ascii=False))
            return
        except Exception as e:
            print(f"[Redis] save_history error: {e}")
        # 3. File
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _serialize_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                result.append(block)
            elif hasattr(block, "type"):
                b = {"type": block.type}
                if block.type == "text":
                    b["text"] = block.text
                elif block.type == "tool_use":
                    b["id"] = block.id
                    b["name"] = block.name
                    b["input"] = dict(block.input)
                elif block.type == "tool_result":
                    b["tool_use_id"] = getattr(block, "tool_use_id", "")
                    b["content"] = getattr(block, "content", "")
                result.append(b)
        return result
    return content

# ── Per-user stats from Redis ────────────────────────────────────────────────

def get_user_stats(user_id: str) -> dict:
    """Read progress + profile for a user from Redis."""
    try:
        nutritionist._current_user_id = user_id
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile  = nutritionist.load_json(nutritionist.PROFILE_FILE)
        logs = progress.get("weight_log", [])
        current_w = logs[-1]["weight_kg"] if logs else profile.get("current_weight_kg", None)
        # Use first weight_log entry as start weight; fall back to profile field
        start_w = logs[0]["weight_kg"] if len(logs) >= 1 else profile.get("current_weight_kg", None)
        target_min = profile.get("target_range", {}).get("min", None)
        target_max = profile.get("target_range", {}).get("max", None)

        # Calculate streak (consecutive days with at least 1 meal logged, shields count)
        from datetime import date, timedelta
        meal_dates = set(m.get("date", "") for m in progress.get("meal_log", []))
        today_iso  = _today()
        month = today_iso[:7]
        try:
            if _db_module.is_available():
                sh = _db_module.db_get_shields(user_id, month)
                shield_dates = set(sh["dates"])
            else:
                raw_shields = _redis_raw_get(f"shields:{user_id}:{month}")
                shield_dates = set(json.loads(raw_shields)) if raw_shields else set()
        except Exception:
            shield_dates = set()
        streak = 0
        check_date = today_iso
        while check_date in meal_dates or check_date in shield_dates:
            streak += 1
            # step back one day using datetime arithmetic
            check_dt = datetime.strptime(check_date, "%Y-%m-%d") - timedelta(days=1)
            check_date = check_dt.strftime("%Y-%m-%d")

        # Calculate today's calories
        today_meals = [m for m in progress.get("meal_log", []) if m.get("date") == today_iso]
        today_calories = sum(m.get("calories_estimate", 0) for m in today_meals)

        measurements = progress.get("measurement_log", [])
        latest_measurements = measurements[-1] if measurements else {}

        referral_count = int(_redis_raw_get(f"referral_count:{user_id}") or 0)
        is_premium = referral_count >= 3

        # Calorie burn
        burn_log = progress.get("burn_log", [])
        today_burn = sum(e["calories"] for e in burn_log if e.get("date") == today_iso)

        return {
            "current_weight": current_w,
            "start_weight": start_w,
            "target_min": target_min,
            "target_max": target_max,
            "lost": round(start_w - current_w, 1) if (start_w and current_w) else None,
            "weight_log": logs[-20:],  # last 20 entries
            "name": profile.get("name", ""),
            "streak": streak,
            "today_calories": today_calories,
            "target_kcal": profile.get("target_kcal", 2100),
            "measurements": latest_measurements,
            "is_premium": is_premium,
            "referral_count": referral_count,
            "diet_mode": profile.get("diet_mode", "balanced"),
            "pregnancy_mode": profile.get("pregnancy_mode", False),
            "pregnancy_week": profile.get("pregnancy_week", 0),
            "today_burn": today_burn,
            "gender": profile.get("gender", "")
        }
    except Exception as e:
        return {}
    finally:
        nutritionist._current_user_id = None

# ── Flask client ─────────────────────────────────────────────────────────────

def get_client():
    global client
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        nutritionist._shared_client = client
    return client

# ── Auth helpers ─────────────────────────────────────────────────────────────

def current_user_id() -> str:
    return session.get("user_id")

def require_login():
    if not current_user_id():
        return redirect(url_for("landing"))
    return None

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if current_user_id():
        return redirect(url_for("app_page"))
    return render_template("index.html")

@app.route("/landing")
def landing():
    return render_template("landing.html")

@app.route("/app")
def app_page():
    redir = require_login()
    if redir:
        return redir
    lang = session.get("lang", "he")
    name = session.get("name", "")
    return render_template("chat.html", lang=lang, user_name=name)

@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = request.get_json()
    result = register_user(
        name=data.get("name", ""),
        email=data.get("email", ""),
        password=data.get("password", ""),
        lang=data.get("lang", "he"),
        phone=data.get("phone", "")
    )
    if result.get("ok"):
        session["user_id"] = result["user_id"]
        session["name"]    = result["name"]
        session["lang"]    = result["lang"]
        session["email"]   = data.get("email", "").lower().strip()
        # Track referral
        ref_code = data.get("ref_code", "")
        if ref_code:
            try:
                if _db_module.is_available():
                    referrer_uid = _db_module.db_get_user_id_by_code(ref_code)
                    if referrer_uid:
                        _db_module.db_increment_referral_count(referrer_uid)
                else:
                    referrer_uid = _redis_raw_get(f"code_to_uid:{ref_code}")
                    if referrer_uid:
                        count = int(_redis_raw_get(f"referral_count:{referrer_uid}") or 0)
                        _redis_raw_set(f"referral_count:{referrer_uid}", str(count + 1))
            except Exception:
                pass
    return jsonify(result)

@app.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json()
    result = login_user(data.get("email", ""), data.get("password", ""))
    if result.get("ok"):
        session["user_id"] = result["user_id"]
        session["name"]    = result["name"]
        session["lang"]    = result.get("lang", "he")
        session["email"]   = data.get("email", "").lower().strip()
    return jsonify(result)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

@app.route("/api/notes")
def api_notes():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    try:
        nutritionist._current_user_id = uid
        # Always use load_json (uses Redis when available, not filesystem check)
        memory = nutritionist.load_json(nutritionist.MEMORY_FILE)
        notes = memory.get("notes", [])
        return jsonify({"notes": list(reversed(notes[-10:]))})
    except Exception as e:
        return jsonify({"notes": []})
    finally:
        nutritionist._current_user_id = None

@app.route("/api/stats")
def api_stats():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    return jsonify(get_user_stats(uid))

@app.route("/api/dashboard")
def api_dashboard():
    """Extended stats for the dashboard view — includes today's meals, macros, weekly calories."""
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    try:
        nutritionist._current_user_id = uid
        from datetime import date, timedelta
        today_iso = _today()  # Israel timezone — matches agent.py log dates

        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile  = nutritionist.load_json(nutritionist.PROFILE_FILE)

        # Today's meals with macros
        raw_meals = [m for m in progress.get("meal_log", []) if m.get("date") == today_iso]
        meal_names = {"breakfast": "ארוחת בוקר", "snack": "חטיף", "lunch": "ארוחת צהריים", "dinner": "ארוחת ערב"}
        today_meals = []
        total_protein = total_carbs = total_fat = 0
        for m in raw_meals:
            p = m.get("protein_g", 0) or 0
            c = m.get("carbs_g", 0) or 0
            f = m.get("fat_g", 0) or 0
            total_protein += p; total_carbs += c; total_fat += f
            today_meals.append({
                "meal_id": m.get("meal_id", "other"),
                "name": meal_names.get(m.get("meal_id", ""), m.get("meal_id", "ארוחה")),
                "time": m.get("time", ""),
                "items": m.get("items", []),
                "calories": m.get("calories_estimate", 0),
                "protein": p, "carbs": c, "fat": f
            })

        # Weekly calories (last 7 days, IL timezone)
        weekly = []
        for i in range(6, -1, -1):
            d = _today_minus(i)
            day_meals = [m for m in progress.get("meal_log", []) if m.get("date") == d]
            kcal = sum(m.get("calories_estimate", 0) for m in day_meals)
            weekly.append({"date": d, "calories": kcal})

        # Water today
        if _db_module.is_available():
            glasses = _db_module.db_get_water(uid, today_iso)
        else:
            water_key = f"{uid}:water:{today_iso}"
            glasses = int(_redis_raw_get(water_key) or 0)

        base = get_user_stats(uid)
        today_calories = base.get("today_calories", 0)
        target_kcal    = profile.get("target_kcal", 2100)
        protein_target = profile.get("target_protein_g", 0) or 0
        meals_logged   = len(set(m.get("meal_id") for m in raw_meals))

        # ── Nutrition Score (0–100, A–F) ──
        protein_pct   = min((total_protein / protein_target * 100), 100) if protein_target > 0 else None
        water_pct     = min((glasses / 8) * 100, 100)
        cal_diff      = abs(today_calories - target_kcal) / max(target_kcal, 1) * 100
        cal_adherence = max(0, 100 - cal_diff)
        meal_score    = min(meals_logged / 3 * 100, 100)

        if protein_pct is not None:
            composite = protein_pct * 0.35 + water_pct * 0.25 + cal_adherence * 0.25 + meal_score * 0.15
        else:
            composite = water_pct * 0.35 + cal_adherence * 0.40 + meal_score * 0.25

        grade = "A" if composite >= 90 else "B" if composite >= 75 else "C" if composite >= 60 else "D" if composite >= 45 else "F"
        grade_color = {"A":"#22c55e","B":"#84cc16","C":"#f59e0b","D":"#f97316","F":"#ef4444"}[grade]

        # ── AI Nudge (rule-based, protein-first) ──
        hour = _now_il().hour
        nudge = None
        if protein_target > 0 and total_protein < protein_target * 0.6:
            shortfall = round(protein_target - total_protein)
            nudge = f"חסרים לך {shortfall}g חלבון להיום — גבינה לבנה 5%, ביצים, או טונה יפתרו את זה"
        elif glasses < 4 and hour >= 14:
            nudge = f"שתית רק {glasses} כוסות מים עד עכשיו — אחר הצהריים זה הזמן המושלם לדביק"
        elif today_calories < target_kcal * 0.45 and hour >= 18:
            nudge = f"אכלת רק {today_calories} קל מתוך {target_kcal} — אל תדלג על ארוחת ערב, זה פוגע בשריר"
        elif today_calories > target_kcal * 1.15:
            over = round(today_calories - target_kcal)
            nudge = f"עברת את היעד ב-{over} קל — ארוחת ערב של חלבון+ירקות תאזן את היום"
        elif base.get("streak", 0) >= 3 and hour >= 20 and not raw_meals:
            nudge = f"🔥 {base.get('streak')} ימים ברצף — דווח על ארוחת הערב כדי לשמור עליו!"
        elif composite >= 85:
            nudge = f"יום מעולה! ציון {grade} — המשך ככה 💪"

        # ── Weekly average weight ──
        logs = base.get("weight_log", [])
        from datetime import timedelta as _td
        cutoff = _today_minus(6)  # 7 days inclusive (today + 6 days back)
        recent_w = [l["weight_kg"] for l in logs if l.get("date","") >= cutoff]
        weekly_avg_weight = round(sum(recent_w)/len(recent_w), 1) if len(recent_w) >= 2 else None

        base.update({
            "today": today_iso,  # IL-timezone date string — used by frontend to highlight correct bar
            "today_meals": today_meals,
            "total_protein": round(total_protein, 1),
            "total_carbs": round(total_carbs, 1),
            "total_fat": round(total_fat, 1),
            "weekly_calories": weekly,
            "water_glasses": glasses,
            "water_target": 8,
            "target_protein_g": protein_target,
            "nutrition_score": {"grade": grade, "color": grade_color, "composite": round(composite, 1)},
            "ai_nudge": nudge,
            "weekly_avg_weight": weekly_avg_weight,
        })
        return jsonify(base)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route("/api/streak-shield", methods=["GET","POST"])
def api_streak_shield():
    uid = current_user_id()
    if not uid: return jsonify({"error": "not logged in"}), 401
    month = _today()[:7]
    if request.method == "GET":
        if _db_module.is_available():
            sh = _db_module.db_get_shields(uid, month)
            used = sh["shield_used"]
        else:
            used = bool(_redis_raw_get(f"shield_used:{uid}:{month}"))
        return jsonify({"used": used, "month": month})
    # POST — activate shield for today
    today = _today()
    if _db_module.is_available():
        sh = _db_module.db_get_shields(uid, month)
        if sh["shield_used"]:
            return jsonify({"ok": False, "msg": "כבר השתמשת במגן החודש הזה"})
        dates = sh["dates"]
        if today not in dates:
            dates.append(today)
        _db_module.db_set_shield(uid, month, dates, True)
    else:
        shield_key = f"shield_used:{uid}:{month}"
        if _redis_raw_get(shield_key):
            return jsonify({"ok": False, "msg": "כבר השתמשת במגן החודש הזה"})
        shields_key = f"shields:{uid}:{month}"
        raw = _redis_raw_get(shields_key)
        shield_dates = json.loads(raw) if raw else []
        if today not in shield_dates:
            shield_dates.append(today)
        _redis_raw_set(shields_key, json.dumps(shield_dates))
        _redis_raw_set(shield_key, "1")
    return jsonify({"ok": True, "msg": "המגן הופעל — הרצף שלך מוגן להיום!"})

# ── Response post-processor ─────────────────────────────────────────────────

def _strip_markdown_tables(text: str) -> str:
    """Remove markdown tables and excess headers from AI responses."""
    lines = text.split('\n')
    cleaned = []
    skip_next_separator = False
    for line in lines:
        stripped = line.strip()
        # Skip table rows (lines that start and end with |)
        if stripped.startswith('|'):
            skip_next_separator = False
            continue
        # Skip standalone markdown headers (# / ## / ###)
        if stripped.startswith('# ') or stripped.startswith('## ') or stripped.startswith('### '):
            continue
        cleaned.append(line)
    # Collapse 3+ consecutive blank lines into 1
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(cleaned))
    return result.strip()

# ── Photo Log v2 helpers ─────────────────────────────────────────────────────

def _detect_meal_id(user_text: str) -> str:
    """Infer meal_id from user text keywords or current time."""
    user_lower = (user_text or "").lower()
    for m in ["breakfast", "snack", "lunch", "dinner"]:
        if m in user_lower:
            return m
    hour = _now_il().hour
    if 6 <= hour < 10:    return "breakfast"
    elif 10 <= hour < 12: return "snack"
    elif 12 <= hour < 16: return "lunch"
    else:                 return "dinner"


def _fast_photo_log(uid: str, raw_b64: str, mime: str, meal_id: str,
                    user_text: str, cl) -> dict:
    """
    Photo Log v2 — single Vision call, direct log_meal, no agentic loop.
    Returns dict: {response, quick_replies, meal_id}
    Target latency: <2.5 sec (vs 3-6 sec for agentic loop).
    """
    extra_ctx = f"\nהקשר נוסף: {user_text}" if user_text else ""
    try:
        vision_resp = cl.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": raw_b64}
                    },
                    {
                        "type": "text",
                        "text": (
                            f"תזונאי מומחה — זהה את האוכל בתמונה והחזר JSON בלבד.{extra_ctx}\n\n"
                            '{"items":[{"name":"שם","amount_g":100,"calories":200,"protein_g":15}],'
                            '"total_calories":200,"total_protein_g":15,"total_carbs_g":20,"total_fat_g":8,'
                            '"confidence":"high"}'
                        )
                    }
                ]
            }]
        )

        raw = vision_resp.content[0].text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return {"response": "❌ לא הצלחתי לנתח את התמונה. נסה שוב.", "quick_replies": []}

        analysis = json.loads(json_match.group())

        items_names = [
            f"{i['name']} ({i.get('amount_g','?')}g)"
            for i in analysis.get("items", [])
        ]
        # Set user context for Redis namespacing
        nutritionist._current_user_id = uid
        nutritionist.log_meal(
            meal_id=meal_id,
            items=items_names,
            calories_estimate=analysis.get("total_calories", 0),
            protein_g=analysis.get("total_protein_g", 0),
            carbs_g=analysis.get("total_carbs_g", 0),
            fat_g=analysis.get("total_fat_g", 0),
        )

        cal   = int(analysis.get("total_calories", 0))
        prot  = int(analysis.get("total_protein_g", 0))
        carbs = int(analysis.get("total_carbs_g", 0))
        conf  = analysis.get("confidence", "medium")
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "🟡")
        meal_he = {"breakfast": "בוקר", "lunch": "צהריים",
                   "dinner": "ערב", "snack": "חטיף", "other": "ארוחה"}.get(meal_id, "ארוחה")

        response_text = (
            f"✅ {meal_he} נרשמה {conf_emoji}\n"
            f"🔥 {cal} קל | 💪 {prot}g חלבון | 🌾 {carbs}g פחמימות"
        )

        # Build meal name for template saving
        items_short = ", ".join(i.get("name","") for i in analysis.get("items",[])[:2])
        template_name = items_short[:20] if items_short else meal_he

        quick_replies = [
            {"label": "➕ הוסף עוד",   "action": "הוסף לארוחה: ",       "type": "prefill"},
            {"label": "✏️ תקן כמות",  "action": "תקן את הכמות של ",     "type": "prefill"},
            {"label": "⭐ שמור תבנית", "action": f"שמור ארוחה זו בשם: {template_name}", "type": "prefill"},
            {"label": "❌ מחק",        "action": f"מחק {meal_id}",        "type": "send"},
            {"label": "📊 דשבורד",    "action": "dashboard",              "type": "view"},
        ]
        return {"response": response_text, "quick_replies": quick_replies, "meal_id": meal_id,
                "_analysis": analysis}

    except Exception as exc:
        import traceback; traceback.print_exc()
        return {"response": f"❌ שגיאה בניתוח תמונה: {exc}", "quick_replies": []}


# ── Chat endpoint ────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
@limiter.limit("30 per minute")
def chat():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401

    # ── Free tier cap check ──────────────────────────────────────────────────
    if not is_paid_user(uid):
        count = get_monthly_message_count(uid)
        if count >= FREE_MONTHLY_CAP:
            _track("paywall_hit", uid, {"messages_used": count, "month": datetime.now().strftime("%Y-%m")})
            return jsonify({
                "error": "free_limit",
                "message": f"הגעת למגבלת {FREE_MONTHLY_CAP} ההודעות החינמיות לחודש זה 🙏\nשדרג לפלוס כדי להמשיך ללא הגבלה.",
                "upgrade_url": "/pricing"
            }), 402

    # ── Increment counter (before heavy LLM call) ────────────────────────────
    if not is_paid_user(uid):
        msg_num = increment_monthly_message_count(uid)
        # Warn at 45/50
        warn_at = FREE_MONTHLY_CAP - 5

    data       = request.get_json()
    user_text  = data.get("message", "").strip()
    image_b64  = data.get("image")
    image_name = data.get("image_name", "food.jpg")

    if not user_text and not image_b64:
        return jsonify({"error": "הודעה ריקה"}), 400

    try:
        # Set user context for Redis namespacing
        nutritionist._current_user_id = uid
        cl = get_client()

        conversation_history = load_history(uid)

        # ── Photo Log v2 fast path ────────────────────────────────────────────
        if image_b64:
            if "," in image_b64:
                header, raw = image_b64.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
            else:
                raw, mime = image_b64, "image/jpeg"

            meal_id = _detect_meal_id(user_text)
            result  = _fast_photo_log(uid, raw, mime, meal_id, user_text, cl)

            # Save lean history entry (no giant base64 blob)
            conversation_history.append({
                "role": "user",
                "content": f"[תמונת אוכל — {meal_id}] {user_text or ''}".strip()
            })
            conversation_history.append({
                "role": "assistant",
                "content": result["response"]
            })
            conversation_history = _safe_truncate(conversation_history, 40)
            save_history(uid, conversation_history)
            _track("chat_message_sent", uid, {
                "has_image": True,
                "paid": is_paid_user(uid),
                "month": datetime.now().strftime("%Y-%m"),
            })

            if not is_paid_user(uid):
                remaining = FREE_MONTHLY_CAP - msg_num
                if 0 < remaining <= 5:
                    result["response"] += (
                        f"\n\n⚠️ נותרו לך {remaining} הודעות חינמיות החודש. "
                        "[שדרג לפלוס ←](/pricing)"
                    )
            return jsonify(result)

        # ── Text-only agentic loop ────────────────────────────────────────────
        content = user_text
        conversation_history.append({"role": "user", "content": content})

        text_parts = []
        loop_completed = False
        for loop_i in range(6):
            response = cl.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=nutritionist.build_system_prompt(),
                tools=nutritionist.TOOLS,
                messages=conversation_history
            )
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                conversation_history.append({"role": "assistant", "content": response.content})
                loop_completed = True
                break

            tool_results = []
            for tu in tool_uses:
                inputs = dict(tu.input)
                if tu.name == "analyze_food_image":
                    inputs["_client"] = cl
                result = nutritionist.execute_tool(tu.name, inputs)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})

            conversation_history.append({"role": "assistant", "content": response.content})
            conversation_history.append({"role": "user", "content": tool_results})
            if response.stop_reason == "end_turn":
                loop_completed = True
                break

        if not loop_completed and not text_parts:
            text_parts.append("✅ הפעולה בוצעה.")

        raw_text   = "".join(text_parts) if text_parts else "✅ פעולה בוצעה!"
        final_text = _strip_markdown_tables(raw_text)

        if not is_paid_user(uid):
            remaining = FREE_MONTHLY_CAP - msg_num
            if 0 < remaining <= 5:
                final_text += f"\n\n⚠️ נותרו לך {remaining} הודעות חינמיות החודש. [שדרג לפלוס ←](/pricing)"

        # Extract weight for stats update
        weight_update = None
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        logs = progress.get("weight_log", [])
        if logs:
            weight_update = logs[-1]["weight_kg"]

        conversation_history = _safe_truncate(conversation_history, 40)
        save_history(uid, conversation_history)
        _track("chat_message_sent", uid, {
            "has_image": False,
            "paid": is_paid_user(uid),
            "month": datetime.now().strftime("%Y-%m"),
        })
        return jsonify({"response": final_text, "weight": weight_update})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route('/static/sw.js')
def sw():
    from flask import send_from_directory
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route("/api/water", methods=["GET", "POST"])
def api_water():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401

    today = _today()
    water_key = f"{uid}:water:{today}"

    if request.method == "POST":
        data = request.get_json()
        action = data.get("action", "add")  # "add" or "reset"
        if _db_module.is_available():
            current = _db_module.db_get_water(uid, today)
        else:
            current = int(_redis_raw_get(water_key) or 0)
        new_val = 0 if action == "reset" else current + 1
        if _db_module.is_available():
            _db_module.db_set_water(uid, today, new_val)
        else:
            _redis_raw_set(water_key, str(new_val))
        return jsonify({"glasses": new_val})
    else:
        if _db_module.is_available():
            glasses = _db_module.db_get_water(uid, today)
        else:
            glasses = int(_redis_raw_get(water_key) or 0)
        return jsonify({"glasses": glasses})

@app.route("/api/calorie-burn", methods=["GET", "POST"])
def api_calorie_burn():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    from datetime import timedelta
    today = _today()
    try:
        nutritionist._current_user_id = uid
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        burn_log = progress.setdefault("burn_log", [])

        if request.method == "POST":
            data = request.get_json()
            action = data.get("action", "add")
            if action == "add":
                activity = data.get("activity", "אחר")
                calories = int(data.get("calories", 0))
                duration_min = int(data.get("duration_min", 0))
                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "date": today,
                    "time": _now_il().strftime("%H:%M"),
                    "activity": activity,
                    "calories": calories,
                    "duration_min": duration_min
                }
                burn_log.append(entry)
                nutritionist.save_json(nutritionist.PROGRESS_FILE, progress)
                today_burn = sum(e["calories"] for e in burn_log if e.get("date") == today)
                return jsonify({"ok": True, "today_burn": today_burn})
            elif action == "delete":
                entry_id = data.get("id")
                if entry_id:
                    # Delete by unique ID (robust — index-independent)
                    before = len(burn_log)
                    progress["burn_log"] = [e for e in burn_log if e.get("id") != entry_id]
                    if len(progress["burn_log"]) < before:
                        nutritionist.save_json(nutritionist.PROGRESS_FILE, progress)
                else:
                    # Fallback: delete by global index (legacy)
                    idx = data.get("index", -1)
                    if 0 <= idx < len(burn_log):
                        burn_log.pop(idx)
                        nutritionist.save_json(nutritionist.PROGRESS_FILE, progress)
                return jsonify({"ok": True})

        # Migrate legacy entries without IDs (backfill uuid so delete works)
        changed = False
        for entry in burn_log:
            if not entry.get("id"):
                entry["id"] = str(uuid.uuid4())[:8]
                changed = True
        if changed:
            nutritionist.save_json(nutritionist.PROGRESS_FILE, progress)

        # GET — return burn data
        # Today
        today_entries = [e for e in burn_log if e.get("date") == today]
        today_burn = sum(e["calories"] for e in today_entries)
        # This week
        week_start = _today_minus(_now_il().weekday())
        week_entries = [e for e in burn_log if e.get("date", "") >= week_start]
        week_burn = sum(e["calories"] for e in week_entries)
        # This month
        month_str = today[:7]
        month_entries = [e for e in burn_log if e.get("date", "").startswith(month_str)]
        month_burn = sum(e["calories"] for e in month_entries)
        return jsonify({
            "today_burn": today_burn,
            "week_burn": week_burn,
            "month_burn": month_burn,
            "today_entries": today_entries,
            "burn_log": burn_log[-30:]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route("/onboarding")
def onboarding():
    if not current_user_id():
        return redirect(url_for("landing"))
    return render_template("onboarding.html")

@app.route("/api/setup-profile", methods=["POST"])
def api_setup_profile():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json()

    try:
        nutritionist._current_user_id = uid
        try:
            existing = nutritionist.load_json(nutritionist.PROFILE_FILE)
        except Exception:
            existing = {}

        # Only overwrite a field if it was explicitly sent in the request
        update_fields = {}
        # Always-present string fields (safe to overwrite with empty)
        update_fields["gender"] = data.get("gender", existing.get("gender", ""))
        update_fields["fav_foods"] = data.get("fav_foods", existing.get("fav_foods", ""))
        update_fields["disliked_foods"] = data.get("disliked_foods", existing.get("disliked_foods", ""))
        update_fields["cooking_level"] = data.get("cooking_level", existing.get("cooking_level", ""))
        update_fields["health_conditions"] = data.get("health_conditions", existing.get("health_conditions", []))
        update_fields["restrictions"] = data.get("restrictions", existing.get("restrictions", []))
        update_fields["meal_frequency"] = data.get("meal_frequency", existing.get("meal_frequency", "3"))
        update_fields["timeline"] = data.get("timeline", existing.get("timeline", ""))
        # Allow manual override of target_kcal from profile edit
        if "target_kcal" in data and data["target_kcal"] is not None and int(data["target_kcal"]) >= 800:
            update_fields["target_kcal"] = int(data["target_kcal"])
            # Also reset base target so pregnancy mode uses new base
            if "_base_target_kcal" in existing:
                existing["_base_target_kcal"] = int(data["target_kcal"])
        else:
            update_fields["target_kcal"] = existing.get("target_kcal", 2100)
        # Numeric fields — only update if explicitly provided (avoids overwriting with hardcoded defaults)
        if "age" in data and data["age"] is not None:
            update_fields["age"] = int(data["age"])
        elif "age" in existing:
            update_fields["age"] = existing["age"]
        if "height_cm" in data and data["height_cm"] is not None:
            update_fields["height_cm"] = int(data["height_cm"])
        elif "height_cm" in existing:
            update_fields["height_cm"] = existing["height_cm"]
        if "current_weight_kg" in data and data["current_weight_kg"] is not None:
            update_fields["current_weight_kg"] = float(data["current_weight_kg"])
            update_fields["target_protein_g"] = int(float(data["current_weight_kg"]) * 2)
        elif "current_weight_kg" in existing:
            update_fields["current_weight_kg"] = existing["current_weight_kg"]
            update_fields["target_protein_g"] = existing.get("target_protein_g", int(float(existing["current_weight_kg"]) * 2))
        existing.update(update_fields)
        # Only update target_range if target_weight was explicitly provided
        if data.get("target_weight"):
            existing["target_range"] = {
                "min": float(data["target_weight"]) - 0.5,
                "max": float(data["target_weight"])
            }
        # Update exercise/wake/sleep only when explicitly provided
        if data.get("exercise"):
            existing["exercise"] = data["exercise"]
        if data.get("wake_time"):
            existing["wake_time"] = data["wake_time"]
        if data.get("sleep_time"):
            existing["sleep_time"] = data["sleep_time"]
        # Keep name from existing or session
        if data.get("name"):
            existing["name"] = data["name"]
        elif not existing.get("name"):
            existing["name"] = session.get("name", "")
        profile = existing

        nutritionist.save_json(nutritionist.PROFILE_FILE, profile)
        # Log weight to weight_log whenever current_weight_kg is provided
        new_weight = data.get("current_weight_kg")
        if new_weight:
            from datetime import date
            progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
            logs = progress.get("weight_log", [])
            new_weight_f = float(new_weight)
            # Only add entry if different from last logged weight
            last_w = logs[-1]["weight_kg"] if logs else None
            if last_w != new_weight_f:
                logs.append({"date": _today(), "weight_kg": new_weight_f, "note": "עדכון פרופיל"})
                progress["weight_log"] = logs
                nutritionist.save_json(nutritionist.PROGRESS_FILE, progress)
    finally:
        nutritionist._current_user_id = None

    return jsonify({"ok": True})

@app.route("/api/link-phone", methods=["POST"])
def api_link_phone():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json()
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "מספר טלפון חסר"})
    _link_phone_to_user(phone, uid)
    # Also update the phone field in the account record so weekly-summary can find it
    email = session.get("email", "")
    if email:
        user = _get_user_by_email(email)
        if user:
            user["phone"] = _phone_digits(phone)
            _save_user(user)
    return jsonify({"ok": True})

@app.route("/api/profile", methods=["GET"])
def api_get_profile():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    try:
        nutritionist._current_user_id = uid
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)
        return jsonify(profile)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route("/api/diet-mode", methods=["POST"])
def api_diet_mode():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json()
    mode = data.get("mode", "balanced")  # balanced/keto/mediterranean/intermittent
    clear_history = data.get("clear_history", True)  # clear conversation on mode switch
    try:
        nutritionist._current_user_id = uid
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)
        old_mode = profile.get("diet_mode", "balanced")
        profile["diet_mode"] = mode
        nutritionist.save_json(nutritionist.PROFILE_FILE, profile)
        # Clear conversation history when switching modes to prevent context bleed
        if clear_history and mode != old_mode:
            save_history(uid, [])
        return jsonify({"ok": True, "mode": mode, "history_cleared": clear_history and mode != old_mode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route("/api/pregnancy-mode", methods=["POST"])
def api_pregnancy_mode():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json()
    enabled = data.get("enabled", False)
    week = int(data.get("week", 0))
    try:
        nutritionist._current_user_id = uid
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)
        profile["pregnancy_mode"] = enabled
        profile["pregnancy_week"] = week
        # Adjust target calories based on trimester
        # Always use stored base to avoid stacking calories on repeat toggles
        if enabled and week > 0:
            trimester = 1 if week <= 13 else (2 if week <= 26 else 3)
            extra = {1: 0, 2: 350, 3: 450}.get(trimester, 0)
            # Save base target once so toggling off/on never accumulates
            if "_base_target_kcal" not in profile:
                profile["_base_target_kcal"] = profile.get("target_kcal", 2100)
            profile["target_kcal"] = profile["_base_target_kcal"] + extra
        elif not enabled:
            # Restore original target_kcal when disabling pregnancy mode
            if "_base_target_kcal" in profile:
                profile["target_kcal"] = profile["_base_target_kcal"]
        nutritionist.save_json(nutritionist.PROFILE_FILE, profile)
        return jsonify({"ok": True, "enabled": enabled, "week": week})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None

@app.route("/reset", methods=["POST"])
def reset():
    uid = current_user_id()
    if uid:
        save_history(uid, [])
    return jsonify({"ok": True})

# ── WhatsApp ─────────────────────────────────────────────────────────────────

def _phone_to_user_id(from_number: str) -> str:
    """Convert 'whatsapp:+972501234567' → UUID if linked, else digits fallback."""
    digits = _phone_digits(from_number)
    # Try to find a registered web account linked to this phone
    linked_uid = _get_user_id_by_phone(digits)
    if linked_uid:
        return linked_uid
    # Fallback: use phone digits as standalone WhatsApp user_id
    return digits

def process_whatsapp_image(user_id: str, media_url: str, caption: str) -> str:
    import urllib.request, urllib.error
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if account_sid and auth_token:
            password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, media_url, account_sid, auth_token)
            handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
            opener  = urllib.request.build_opener(handler)
            with opener.open(media_url, timeout=15) as resp:
                image_data = resp.read()
        else:
            with urllib.request.urlopen(media_url, timeout=15) as resp:
                image_data = resp.read()

        image_b64 = base64.b64encode(image_data).decode("utf-8")
        prompt = caption if caption else "נתח את האוכל בתמונה: מה יש כאן? כמה קלוריות? כמה חלבון?"

        history = load_history(user_id)
        history.append({"role": "user", "content": f"[WhatsApp תמונה] {prompt}"})

        # Determine meal_id from caption or time of day (IL timezone)
        hour = _now_il().hour
        meal_id = "other"
        for m in ["breakfast", "snack", "lunch", "dinner"]:
            if m in (caption or "").lower():
                meal_id = m
                break
        if meal_id == "other":
            if 6 <= hour < 10:    meal_id = "breakfast"
            elif 10 <= hour < 12: meal_id = "snack"
            elif 12 <= hour < 16: meal_id = "lunch"
            else:                 meal_id = "dinner"

        vision_prompt = f"""נתח את תמונת האוכל. ענה בפורמט JSON בלבד:
{{
  "items": [{{"name": "שם", "amount_g": 100, "calories": 200, "protein_g": 20}}],
  "total_calories": 400,
  "total_protein_g": 40,
  "total_carbs_g": 30,
  "total_fat_g": 15,
  "description": "תיאור קצר"
}}
{f'הקשר: {caption}' if caption else ''}"""

        response = nutritionist._shared_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text",  "text": vision_prompt}
            ]}]
        )
        raw_reply = response.content[0].text
        # Try to parse JSON and log the meal automatically
        try:
            json_match = re.search(r'\{.*\}', raw_reply, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
                items_names = [f"{i['name']} ({i.get('amount_g','?')}g)" for i in analysis.get("items", [])]
                nutritionist.log_meal(
                    meal_id=meal_id,
                    items=items_names,
                    calories_estimate=analysis.get("total_calories", 0),
                    protein_g=analysis.get("total_protein_g", 0),
                    carbs_g=analysis.get("total_carbs_g", 0),
                    fat_g=analysis.get("total_fat_g", 0),
                )
                desc = analysis.get("description", "")
                total_cal = analysis.get("total_calories", 0)
                total_prot = analysis.get("total_protein_g", 0)
                reply = f"📸 {desc}\n✅ נרשם: {total_cal} קל | חלבון {total_prot}g"
            else:
                reply = raw_reply
        except Exception:
            reply = raw_reply

        history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        history = _safe_truncate(history, 40)
        save_history(user_id, history)
        return reply
    except Exception as e:
        return f"לא הצלחתי לקרוא את התמונה: {e}"

def _check_streak_viral(user_id: str) -> str | None:
    """
    Returns a viral WhatsApp message when user hits a streak milestone (3/7/14/21/30 days).
    Returns None when no milestone reached or already sent today.
    """
    MILESTONES = {3: "🔥", 7: "🏆", 14: "💎", 21: "🚀", 30: "👑"}
    nutritionist._current_user_id = user_id
    progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
    meal_dates = set(m.get("date", "") for m in progress.get("meal_log", []))
    streak = 0
    check = _today()
    from datetime import timedelta
    while check in meal_dates:
        streak += 1
        check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    if streak not in MILESTONES:
        return None

    # Avoid sending twice on same day
    if _db_module.is_available():
        if _db_module.db_viral_already_sent(user_id, streak):
            return None
        _db_module.db_mark_viral_sent(user_id, streak, _today())
    else:
        sent_key = f"streak_viral:{user_id}:{streak}"
        if _redis_raw_get(sent_key):
            return None
        _redis_raw_set(sent_key, "1")

    emoji = MILESTONES[streak]
    code = _get_or_create_referral_code(user_id)
    base_url = os.environ.get("APP_BASE_URL", "https://nutritionist-agent-ouvp.onrender.com")
    ref_url = f"{base_url}/landing?ref={code}"
    return (
        f"{emoji} *{streak} ימים ברצף!*\n"
        f"הישג מדהים 💪 שתף/י עם חבר/ה שיכול/ה להצטרף:\n{ref_url}"
    )


def process_for_whatsapp(user_id: str, user_text: str) -> str:
    nutritionist._current_user_id = user_id
    try:
        history = load_history(user_id)
        history.append({"role": "user", "content": f"[WhatsApp] {user_text}"})
        cl = get_client()
        text_parts = []

        for _ in range(6):
            response = cl.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=nutritionist.build_system_prompt(),
                tools=nutritionist.TOOLS,
                messages=history
            )
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                history.append({"role": "assistant", "content": response.content})
                break

            tool_results = []
            for tu in tool_uses:
                inputs = dict(tu.input)
                if tu.name == "analyze_food_image":
                    inputs["_client"] = cl
                result = nutritionist.execute_tool(tu.name, inputs)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})

            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": tool_results})
            if response.stop_reason == "end_turn":
                break

        history = _safe_truncate(history, 40)
        save_history(user_id, history)

        reply = "".join(text_parts) if text_parts else "✅ בוצע!"
        reply = re.sub(r'\*\*(.+?)\*\*', r'*\1*', reply)
        reply = re.sub(r'#{1,3} (.+)', r'*\1*', reply)

        # ── WhatsApp viral hook: streak milestones ──
        try:
            viral = _check_streak_viral(user_id)
            if viral:
                reply = reply + "\n\n" + viral
        except Exception:
            pass

        return reply
    finally:
        nutritionist._current_user_id = None

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number  = request.values.get("From", "unknown")
        num_media    = int(request.values.get("NumMedia", "0"))
        user_id      = _phone_to_user_id(from_number)

        print(f"[WhatsApp] user:{user_id} | msg:{incoming_msg[:60]} | media:{num_media}")

        get_client()  # ensure client initialized

        if num_media > 0:
            media_url          = request.values.get("MediaUrl0", "")
            media_content_type = request.values.get("MediaContentType0", "")
            if media_url and "image" in media_content_type:
                reply = process_whatsapp_image(user_id, media_url, incoming_msg)
                return _twilio_reply(reply)

        if not incoming_msg:
            return _twilio_reply("שלום! שלח לי הודעה ואשמח לעזור 🥗")

        reply = process_for_whatsapp(user_id, incoming_msg)
        return _twilio_reply(reply)

    except Exception as e:
        import traceback; traceback.print_exc()
        return _twilio_reply(f"שגיאה: {e}")

def _twilio_reply(text: str) -> Response:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{text}</Message>
</Response>"""
    return Response(xml, mimetype="text/xml")

def _send_whatsapp(to_phone: str, message: str):
    """Send WhatsApp message via Twilio REST API"""
    import urllib.request, urllib.parse, base64
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not account_sid or not auth_token:
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    digits = re.sub(r'\D', '', to_phone)
    if not digits.startswith('0') and not digits.startswith('+'):
        wa_to = f"whatsapp:+{digits}"
    else:
        wa_to = f"whatsapp:+{digits.lstrip('0')}" if digits.startswith('0') else f"whatsapp:{digits}"

    data = urllib.parse.urlencode({
        "From": "whatsapp:+14155238886",
        "To": wa_to,
        "Body": message
    }).encode()

    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 201
    except Exception as e:
        print(f"[Twilio] send error: {e}")
        return False


def _generate_weekly_summary(user_id: str, user_name: str) -> str:
    """Generate a personalized weekly summary message"""
    from datetime import date, timedelta
    nutritionist._current_user_id = user_id
    try:
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)

        # Last 7 days of data
        seven_days_ago = _today_minus(7)
        recent_meals = [m for m in progress.get("meal_log", []) if m.get("date", "") >= seven_days_ago]
        recent_weights = [w for w in progress.get("weight_log", []) if w.get("date", "") >= seven_days_ago]

        total_days_logged = len(set(m.get("date") for m in recent_meals))
        total_calories = sum(m.get("calories_estimate", 0) for m in recent_meals)
        avg_daily_calories = total_calories // 7 if total_calories else 0

        latest_weight = recent_weights[-1]["weight_kg"] if recent_weights else profile.get("current_weight_kg", "?")
        target = profile.get("target_range", {}).get("max") or profile.get("target_weight_kg") or "לא הוגדר"

        msg = f"""📊 *סיכום שבועי — NutriAI*
שלום {user_name}! הנה הסיכום שלך לשבוע:

⚖️ משקל נוכחי: {latest_weight} ק"ג (יעד: {target} ק"ג)
🍽️ ימים עם דיווח: {total_days_logged}/7
🔥 ממוצע קלוריות יומי: {avg_daily_calories} קל

"""
        if total_days_logged >= 5:
            msg += "✅ שבוע מעולה! המשך כך!\n"
        elif total_days_logged >= 3:
            msg += "👍 שבוע סביר — נסה לדווח יותר ימים!\n"
        else:
            msg += "💪 השבוע הבא נתחיל מחדש — כל יום חשוב!\n"

        # Referral viral hook
        code = _get_or_create_referral_code(user_id)
        base_url = os.environ.get("APP_BASE_URL", "https://nutritionist-agent-ouvp.onrender.com")
        referral_url = f"{base_url}/landing?ref={code}"
        msg += f"\n📲 הזמן חבר/ה וקבל חודש פלוס בחינם:\n{referral_url}"
        return msg
    finally:
        nutritionist._current_user_id = None


_migration_status = {"running": False, "done": False, "stats": {}}

@app.route("/api/migrate-redis-to-pg", methods=["POST"])
def api_migrate_redis_to_pg():
    """One-time migration: copy all Redis data to Postgres. Runs in background thread."""
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.environ.get("CRON_SECRET", "nutriai-cron-2026"):
        return jsonify({"error": "unauthorized"}), 401
    if not _db_module.is_available():
        return jsonify({"error": "DATABASE_URL not configured"}), 500

    redis_url   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    redis_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not redis_url or not redis_token:
        return jsonify({"error": "Redis env vars not set"}), 500

    if _migration_status["running"]:
        return jsonify({"status": "already_running", "stats": _migration_status["stats"]})
    if _migration_status["done"]:
        return jsonify({"status": "already_done", "stats": _migration_status["stats"]})

    def _run_migration():
        import urllib.request as ureq
        _migration_status["running"] = True
        stats = {"users": 0, "histories": 0, "blobs": 0, "water": 0,
                 "shields": 0, "referrals": 0, "counts": 0, "errors": []}

        def r_get(key):
            try:
                req = ureq.Request(f"{redis_url}/get/{key}",
                                   headers={"Authorization": f"Bearer {redis_token}"})
                with ureq.urlopen(req, timeout=6) as resp:
                    return json.loads(resp.read()).get("result")
            except Exception:
                return None

        def r_scan(pattern):
            keys = []
            cursor = 0
            while True:
                try:
                    req = ureq.Request(
                        f"{redis_url}/scan/{cursor}/match/{pattern}/count/100",
                        headers={"Authorization": f"Bearer {redis_token}"}
                    )
                    with ureq.urlopen(req, timeout=6) as resp:
                        result = json.loads(resp.read())["result"]
                    cursor = int(result[0])
                    keys.extend(result[1])
                    if cursor == 0:
                        break
                except Exception:
                    break
            return keys

        user_ids = []
        DATA_KEYS = ["progress", "user_profile", "agent_memory", "meal_plan"]

        try:
            # 1. Users
            for key in r_scan("account:*"):
                raw = r_get(key)
                if not raw:
                    continue
                try:
                    user = json.loads(raw)
                    _db_module.db_save_user(user)
                    uid = user.get("id")
                    if uid:
                        user_ids.append(uid)
                    stats["users"] += 1
                except Exception as e:
                    stats["errors"].append(f"user {key}: {e}")

            # 2. Per-user data
            for uid in user_ids:
                # History
                raw = r_get(f"{uid}:conversation_history")
                if raw:
                    try:
                        _db_module.db_save_history(uid, json.loads(raw))
                        stats["histories"] += 1
                    except Exception as e:
                        stats["errors"].append(f"hist {uid}: {e}")
                # JSON blobs
                for blob_key in DATA_KEYS:
                    raw = r_get(f"{uid}:{blob_key}")
                    if raw:
                        try:
                            _db_module.db_save_json(uid, blob_key, json.loads(raw))
                            stats["blobs"] += 1
                        except Exception as e:
                            stats["errors"].append(f"blob {uid}:{blob_key}: {e}")
                # Referral
                code = r_get(f"referral_code:{uid}")
                if code:
                    try:
                        _db_module.db_create_referral_code(uid, code)
                        count_raw = r_get(f"referral_count:{uid}")
                        if count_raw and int(count_raw) > 0:
                            _db_module._exec("UPDATE referrals SET count=%s WHERE user_id=%s",
                                             (int(count_raw), uid))
                        stats["referrals"] += 1
                    except Exception as e:
                        stats["errors"].append(f"ref {uid}: {e}")
                # Stripe
                status = r_get(f"stripe_sub:{uid}")
                if status:
                    try:
                        _db_module.db_set_stripe_status(uid, status)
                    except Exception as e:
                        stats["errors"].append(f"stripe {uid}: {e}")
                # Msg counts (current month only)
                month = datetime.now().strftime("%Y-%m")
                count_raw = r_get(f"msg_count:{uid}:{month}")
                if count_raw:
                    try:
                        _db_module._exec(
                            "INSERT INTO message_counts(user_id,month,count) VALUES(%s,%s,%s) "
                            "ON CONFLICT(user_id,month) DO UPDATE SET count=EXCLUDED.count",
                            (uid, month, int(count_raw))
                        )
                        stats["counts"] += 1
                    except Exception as e:
                        stats["errors"].append(f"count {uid}: {e}")
                # Water (today only)
                from datetime import date as _date
                today_str = _today()
                water_raw = r_get(f"{uid}:water:{today_str}")
                if water_raw:
                    try:
                        _db_module.db_set_water(uid, today_str, int(water_raw))
                        stats["water"] += 1
                    except Exception as e:
                        stats["errors"].append(f"water {uid}: {e}")
                # Shields (current month)
                shields_raw = r_get(f"shields:{uid}:{month}")
                if shields_raw:
                    try:
                        used = bool(r_get(f"shield_used:{uid}:{month}"))
                        _db_module.db_set_shield(uid, month, json.loads(shields_raw), used)
                        stats["shields"] += 1
                    except Exception as e:
                        stats["errors"].append(f"shield {uid}: {e}")

        except Exception as e:
            stats["errors"].append(f"fatal: {e}")

        _migration_status["running"] = False
        _migration_status["done"] = True
        _migration_status["stats"] = stats
        print(f"[Migration] complete: {stats}")

    import threading
    threading.Thread(target=_run_migration, daemon=True).start()
    return jsonify({"status": "started", "message": "Migration running in background. Poll /api/migrate-status to check."})


@app.route("/api/migrate-status", methods=["GET"])
def api_migrate_status():
    """Check migration progress."""
    return jsonify(_migration_status)


@app.route("/api/weekly-summary", methods=["POST"])
def weekly_summary():
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.environ.get("CRON_SECRET", "nutriai-cron-2026"):
        return jsonify({"error": "unauthorized"}), 401

    sent = 0
    if _db_module.is_available():
        users = _db_module.db_all_users_with_phones()
        for u in users:
            msg = _generate_weekly_summary(u["id"], u["name"])
            if _send_whatsapp(u["phone"], msg):
                sent += 1
    else:
        import urllib.request as ureq
        url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
        scan_req = ureq.Request(f"{url}/scan/0/match/account:*/count/100",
                                headers={"Authorization": f"Bearer {token}"})
        with ureq.urlopen(scan_req, timeout=5) as resp:
            keys = json.loads(resp.read())["result"][1]
        for key in keys:
            raw = _redis_raw_get(key)
            if not raw:
                continue
            user = json.loads(raw)
            phone = user.get("phone", "")
            if not phone:
                continue
            user_id = user.get("id")
            name = user.get("name", "משתמש")
            msg = _generate_weekly_summary(user_id, name)
            if _send_whatsapp(phone, msg):
                sent += 1

    return jsonify({"ok": True, "sent": sent})


@app.route("/api/shopping-list", methods=["GET"])
def api_shopping_list():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401

    try:
        nutritionist._current_user_id = uid
        cl = get_client()

        meal_plan = nutritionist.load_json(nutritionist.MEAL_PLAN_FILE)
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)

        plan_text = json.dumps(meal_plan, ensure_ascii=False) if meal_plan else "אין תפריט שבועי מוגדר"

        response = cl.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": f"""בהתבסס על התפריט השבועי הזה, צור רשימת קניות מסודרת בעברית.

תפריט: {plan_text}

פרופיל: גיל {profile.get('age','?')}, משקל {profile.get('current_weight_kg','?')}ק"ג, יעד {profile.get('target_kcal',2100)} קל/יום

פרמט את הרשימה לפי קטגוריות:
🥩 בשר ודגים
🥚 ביצים ומוצרי חלב
🥦 ירקות ופירות
🌾 דגנים וקטניות
🫙 שימורים ויבשים
🧴 אחר

כתוב כמויות מדויקות לשבוע אחד. תשובה בעברית בלבד."""}]
        )

        shopping_text = response.content[0].text
        return jsonify({"ok": True, "list": shopping_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None


@app.route("/report")
def report():
    uid = current_user_id()
    if not uid:
        return redirect(url_for("landing"))

    from datetime import date, timedelta
    nutritionist._current_user_id = uid
    try:
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile = nutritionist.load_json(nutritionist.PROFILE_FILE)

        seven_days_ago = _today_minus(7)
        recent_meals = [m for m in progress.get("meal_log", []) if m.get("date","") >= seven_days_ago]
        weight_log = progress.get("weight_log", [])[-10:]

        # Group meals by date
        from collections import defaultdict
        meals_by_day = defaultdict(list)
        for m in recent_meals:
            meals_by_day[m["date"]].append(m)

        total_cal = sum(m.get("calories_estimate",0) for m in recent_meals)
        days_logged = len(meals_by_day)
        avg_cal = total_cal // days_logged if days_logged else 0

        latest_weight = weight_log[-1]["weight_kg"] if weight_log else profile.get("current_weight_kg","?")
        start_weight = weight_log[0]["weight_kg"] if len(weight_log) > 1 else latest_weight

        return render_template("report.html",
            profile=profile,
            meals_by_day=dict(sorted(meals_by_day.items())),
            weight_log=weight_log,
            total_cal=total_cal,
            avg_cal=avg_cal,
            days_logged=days_logged,
            latest_weight=latest_weight,
            start_weight=start_weight,
            name=session.get("name",""),
            report_date=_today()
        )
    finally:
        nutritionist._current_user_id = None


@app.route("/gallery")
def gallery():
    uid = current_user_id()
    if not uid:
        return redirect(url_for("landing"))
    nutritionist._current_user_id = uid
    try:
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        meals = sorted(progress.get("meal_log", []), key=lambda m: (m.get("date",""), m.get("time","")), reverse=True)
        return render_template("gallery.html", meals=meals, name=session.get("name",""))
    finally:
        nutritionist._current_user_id = None


def _get_or_create_referral_code(uid: str) -> str:
    if _db_module.is_available():
        code = _db_module.db_get_referral_code(uid)
        if not code:
            import random, string
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = _db_module.db_create_referral_code(uid, code)
        return code
    # Redis fallback
    key = f"referral_code:{uid}"
    code = _redis_raw_get(key)
    if not code:
        import random, string
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        _redis_raw_set(key, code)
        _redis_raw_set(f"code_to_uid:{code}", uid)
    return code


@app.route("/api/referral", methods=["GET"])
def api_referral():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    code = _get_or_create_referral_code(uid)
    if _db_module.is_available():
        referrals = _db_module.db_get_referral_count(uid)
    else:
        referrals = int(_redis_raw_get(f"referral_count:{uid}") or 0)
    base_url = os.environ.get("APP_BASE_URL", "https://nutritionist-agent-ouvp.onrender.com")
    link = f"{base_url}/landing?ref={code}"
    return jsonify({"code": code, "link": link, "referrals": referrals})


# ── Meal Templates API ───────────────────────────────────────────────────────

@app.route("/api/templates", methods=["GET"])
def api_templates_list():
    uid = current_user_id()
    if not uid:
        return jsonify([])
    nutritionist._current_user_id = uid
    memory = nutritionist.load_json(nutritionist.MEMORY_FILE)
    templates = memory.get("meal_templates", [])
    # Sort by use_count descending
    templates.sort(key=lambda t: t.get("use_count", 0), reverse=True)
    return jsonify(templates)


@app.route("/api/templates/<template_id>/log", methods=["POST"])
def api_log_template(template_id):
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    nutritionist._current_user_id = uid
    memory = nutritionist.load_json(nutritionist.MEMORY_FILE)
    templates = memory.get("meal_templates", [])
    tmpl = next((t for t in templates if t["id"] == template_id), None)
    if not tmpl:
        return jsonify({"error": "template not found"}), 404

    nutritionist.log_meal(
        meal_id=tmpl["meal_id"],
        items=tmpl["items"],
        calories_estimate=tmpl.get("calories", 0),
        protein_g=tmpl.get("protein_g", 0),
        carbs_g=tmpl.get("carbs_g", 0),
        fat_g=tmpl.get("fat_g", 0),
    )
    # Increment use count
    idx = next((i for i, t in enumerate(templates) if t["id"] == template_id), None)
    if idx is not None:
        templates[idx]["use_count"] = templates[idx].get("use_count", 0) + 1
        nutritionist.save_json(nutritionist.MEMORY_FILE, memory)

    cal  = int(tmpl.get("calories", 0))
    prot = int(tmpl.get("protein_g", 0))
    meal_he = {"breakfast": "בוקר", "lunch": "צהריים", "dinner": "ערב",
               "snack": "חטיף", "other": "ארוחה"}.get(tmpl["meal_id"], "ארוחה")
    return jsonify({
        "response": f"✅ {tmpl['name']} נרשמה — {cal} קל | {prot}g חלבון",
        "quick_replies": [
            {"label": "❌ מחק", "action": f"מחק {tmpl['meal_id']}", "type": "send"},
            {"label": "📊 דשבורד", "action": "dashboard", "type": "view"},
        ]
    })


@app.route("/api/templates/<template_id>", methods=["DELETE"])
def api_delete_template(template_id):
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    nutritionist._current_user_id = uid
    memory = nutritionist.load_json(nutritionist.MEMORY_FILE)
    templates = memory.get("meal_templates", [])
    memory["meal_templates"] = [t for t in templates if t["id"] != template_id]
    nutritionist.save_json(nutritionist.MEMORY_FILE, memory)
    return jsonify({"ok": True})


# ── Day Log API — meals/macros for any past date ────────────────────────────

@app.route("/api/day-log", methods=["GET"])
def api_day_log():
    """Return meals and macros for a specific date (YYYY-MM-DD). Defaults to today."""
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    date_str = request.args.get("date", _today())
    # Validate format
    import re as _re
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return jsonify({"error": "invalid date format"}), 400
    try:
        nutritionist._current_user_id = uid
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile  = nutritionist.load_json(nutritionist.PROFILE_FILE)

        meal_names = {"breakfast": "ארוחת בוקר", "snack": "חטיף",
                      "lunch": "ארוחת צהריים", "dinner": "ארוחת ערב"}
        raw_meals = [m for m in progress.get("meal_log", []) if m.get("date") == date_str]
        meals = []
        total_cal = total_prot = total_carbs = total_fat = 0
        for m in raw_meals:
            p = m.get("protein_g", 0) or 0
            c = m.get("carbs_g", 0) or 0
            f = m.get("fat_g", 0) or 0
            cal = m.get("calories_estimate", 0) or 0
            total_cal += cal; total_prot += p; total_carbs += c; total_fat += f
            meals.append({
                "meal_id": m.get("meal_id", "other"),
                "name": meal_names.get(m.get("meal_id", ""), "ארוחה"),
                "time": m.get("time", ""),
                "items": m.get("items", []),
                "calories": cal,
                "protein": p, "carbs": c, "fat": f
            })

        # Weight log for this date
        weight_entry = next(
            (w for w in reversed(progress.get("weight_log", [])) if w.get("date") == date_str),
            None
        )

        # Water for this date
        if _db_module.is_available():
            water = _db_module.db_get_water(uid, date_str)
        else:
            water = int(_redis_raw_get(f"{uid}:water:{date_str}") or 0)

        # Burn log for this date
        burn_entries = [e for e in progress.get("burn_log", []) if e.get("date") == date_str]
        total_burn = sum(e.get("calories", 0) for e in burn_entries)

        target_kcal = profile.get("target_kcal", 2100)
        target_prot = profile.get("target_protein_g", 0) or 0

        return jsonify({
            "date": date_str,
            "meals": meals,
            "total_calories": round(total_cal),
            "total_protein": round(total_prot, 1),
            "total_carbs": round(total_carbs, 1),
            "total_fat": round(total_fat, 1),
            "water_glasses": water,
            "total_burn": total_burn,
            "burn_entries": burn_entries,
            "weight": weight_entry,
            "target_kcal": target_kcal,
            "target_protein_g": target_prot,
            "is_today": date_str == _today(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        nutritionist._current_user_id = None


# ── Weekly Story Share API ────────────────────────────────────────────────────

@app.route("/api/story", methods=["GET"])
def api_story():
    """Generate a shareable weekly story summary (text for WhatsApp / social)."""
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    try:
        nutritionist._current_user_id = uid
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        profile  = nutritionist.load_json(nutritionist.PROFILE_FILE)

        seven_days_ago = _today_minus(7)
        recent_meals   = [m for m in progress.get("meal_log", []) if m.get("date","") >= seven_days_ago]
        days_logged    = len(set(m.get("date") for m in recent_meals))
        avg_cal        = int(sum(m.get("calories_estimate",0) for m in recent_meals) / 7) if recent_meals else 0
        avg_prot       = int(sum(m.get("protein_g",0) for m in recent_meals) / max(days_logged,1))

        logs = progress.get("weight_log", [])
        current_w = logs[-1]["weight_kg"] if logs else profile.get("current_weight_kg","?")
        start_w   = logs[0]["weight_kg"]  if logs else current_w
        lost      = round(float(start_w) - float(current_w), 1) if start_w and current_w else 0

        # Streak
        meal_dates = set(m.get("date","") for m in progress.get("meal_log",[]))
        streak = 0
        check  = _today()
        from datetime import timedelta
        while check in meal_dates:
            streak += 1
            check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        name = profile.get("name","") or session.get("name","")
        grade_emoji = "🏆" if days_logged >= 6 else "💪" if days_logged >= 4 else "📈"

        story = (
            f"{grade_emoji} *הסיכום השבועי שלי — NutriAI*\n\n"
            f"👤 {name}\n"
            f"🔥 רצף: {streak} ימים\n"
            f"🍽️ ימי דיווח: {days_logged}/7\n"
            f"⚡ ממוצע יומי: {avg_cal} קל | {avg_prot}g חלבון\n"
            f"⚖️ ירידה כוללת: {lost} ק\"ג\n\n"
            f"המאמן התזונתי שלי 👉 nutri-ai.app"
        )
        code    = _get_or_create_referral_code(uid)
        base    = os.environ.get("APP_BASE_URL","https://nutritionist-agent-ouvp.onrender.com")
        ref_url = f"{base}/landing?ref={code}"
        story  += f"\n📲 {ref_url}"

        return jsonify({"story": story, "streak": streak, "days_logged": days_logged,
                        "avg_cal": avg_cal, "lost": lost})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "service": "nutritionist-agent"}), 200


@app.route("/healthz")
def healthz():
    """Render health check endpoint"""
    return jsonify({"healthy": True}), 200


@app.route("/api/lang", methods=["POST"])
def set_language():
    data = request.get_json()
    lang = data.get("lang", "he")
    if lang in ("he", "en"):
        session["lang"] = lang
    return jsonify({"ok": True, "lang": session.get("lang", "he")})


# ── Stripe / Payments ─────────────────────────────────────────────────────────

# Pricing tiers — price IDs are set via env vars (Stripe Dashboard)
STRIPE_PLANS = {
    "plus_monthly":  {"name": "Plus",   "price_env": "STRIPE_PRICE_PLUS_MONTHLY",  "amount": "$5.99/mo",  "tier": "plus"},
    "plus_yearly":   {"name": "Plus",   "price_env": "STRIPE_PRICE_PLUS_YEARLY",   "amount": "$59.99/yr", "tier": "plus"},
    "family_monthly":{"name": "Family", "price_env": "STRIPE_PRICE_FAMILY_MONTHLY","amount": "$14.99/mo", "tier": "family"},
    "family_yearly": {"name": "Family", "price_env": "STRIPE_PRICE_FAMILY_YEARLY", "amount": "$179.99/yr","tier": "family"},
}

@app.route("/pricing")
def pricing():
    uid = current_user_id()
    plan = _redis_raw_get(f"stripe_plan:{uid}") if uid else None
    return render_template("pricing.html", current_plan=plan or "free")

@app.route("/stripe/create-checkout-session", methods=["POST"])
def stripe_create_checkout():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    try:
        import stripe
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            return jsonify({"error": "Stripe not configured"}), 503

        data      = request.get_json()
        plan_key  = data.get("plan", "plus_monthly")
        plan_info = STRIPE_PLANS.get(plan_key)
        if not plan_info:
            return jsonify({"error": "Invalid plan"}), 400

        price_id = os.environ.get(plan_info["price_env"])
        if not price_id:
            return jsonify({"error": f"Price not configured for {plan_key}"}), 503

        email = session.get("email", "")
        base_url = request.host_url.rstrip("/")

        # Retrieve or create Stripe customer
        customer_id = _redis_raw_get(f"stripe_customer:{uid}")
        if not customer_id:
            customer = stripe.Customer.create(
                email=email,
                metadata={"uid": uid, "name": session.get("name", "")}
            )
            customer_id = customer.id
            _redis_raw_set(f"stripe_customer:{uid}", customer_id)

        checkout = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{base_url}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/pricing?cancelled=1",
            metadata={"uid": uid, "plan_key": plan_key, "tier": plan_info["tier"]},
            subscription_data={"metadata": {"uid": uid, "tier": plan_info["tier"]}},
            allow_promotion_codes=True,
        )
        _track("checkout_started", uid, {"plan": plan_key, "tier": plan_info["tier"]})
        return jsonify({"checkout_url": checkout.url})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/stripe/success")
def stripe_success():
    return render_template("stripe_success.html")

@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    ev_type = event["type"]

    # Helper: extract uid from subscription metadata
    def _uid_from_sub(sub):
        return (sub.get("metadata") or {}).get("uid")

    if ev_type in ("customer.subscription.created", "customer.subscription.updated"):
        sub    = event["data"]["object"]
        uid    = _uid_from_sub(sub)
        status = sub.get("status")          # active, past_due, canceled, etc.
        tier   = (sub.get("metadata") or {}).get("tier", "plus")
        if uid:
            _redis_raw_set(f"stripe_sub:{uid}", status)
            _redis_raw_set(f"stripe_plan:{uid}", tier if status == "active" else "free")

    elif ev_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        uid = _uid_from_sub(sub)
        if uid:
            _redis_raw_set(f"stripe_sub:{uid}", "canceled")
            _redis_raw_set(f"stripe_plan:{uid}", "free")

    elif ev_type == "invoice.payment_failed":
        sub_id = event["data"]["object"].get("subscription")
        if sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                uid = _uid_from_sub(sub)
                if uid:
                    _redis_raw_set(f"stripe_sub:{uid}", "past_due")
            except Exception:
                pass

    return jsonify({"received": True}), 200

@app.route("/api/subscription-status")
def api_subscription_status():
    uid = current_user_id()
    if not uid:
        return jsonify({"plan": "free", "paid": False})
    paid   = is_paid_user(uid)
    plan   = _redis_raw_get(f"stripe_plan:{uid}") or ("plus" if paid else "free")
    status = _redis_raw_get(f"stripe_sub:{uid}") or "none"
    count  = get_monthly_message_count(uid)
    remaining = max(0, FREE_MONTHLY_CAP - count) if not paid else None
    return jsonify({"plan": plan, "paid": paid, "status": status,
                    "messages_used": count, "messages_remaining": remaining})

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    print("=" * 50)
    print("  Smart Nutritionist Agent - Multi-User Web UI")
    print("  http://localhost:5000")
    print("=" * 50)

    import webbrowser, threading
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
