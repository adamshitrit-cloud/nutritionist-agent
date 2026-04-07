"""
Flask web server for the Smart Nutritionist Agent — Multi-user edition.
Supports WhatsApp (Twilio) + web UI with per-user isolated Redis storage.
"""
from flask import (Flask, render_template, request, jsonify,
                   Response, session, redirect, url_for)
import anthropic
import json, os, sys, base64, re, hashlib, secrets, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import agent as nutritionist

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "conversation_history.json"

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

client = None

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

# ── User accounts (stored in Redis) ─────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def _get_user_by_email(email: str) -> dict:
    try:
        raw = _redis_raw_get(f"account:{email.lower()}")
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _save_user(user: dict):
    try:
        _redis_raw_set(f"account:{user['email'].lower()}", json.dumps(user, ensure_ascii=False))
    except Exception as e:
        print(f"[Auth] save_user error: {e}")

def _phone_digits(phone: str) -> str:
    """Strip all non-digits from a phone number. '05X-XXX' → '05XXXX', 'whatsapp:+972...' → '972...'"""
    return re.sub(r'\D', '', phone)

def _link_phone_to_user(phone: str, user_id: str):
    """Store phone→user_id mapping in Redis so WhatsApp messages find the right account."""
    digits = _phone_digits(phone)
    if digits:
        try:
            _redis_raw_set(f"phone:{digits}", user_id)
        except Exception as e:
            print(f"[Auth] link_phone error: {e}")

def _get_user_id_by_phone(phone: str) -> str | None:
    """Look up user_id from phone number digits. Returns None if not found."""
    digits = _phone_digits(phone)
    if not digits:
        return None
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
    return {"ok": True, "user_id": user["id"], "name": user["name"], "lang": lang}

def login_user(email: str, password: str) -> dict:
    """Returns {'ok': True, 'user_id': ...} or {'error': '...'}"""
    user = _get_user_by_email(email.lower().strip())
    if not user:
        return {"error": "המייל לא נמצא" }
    if _hash_password(password, user["salt"]) != user["password_hash"]:
        return {"error": "סיסמה שגויה"}
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
    try:
        raw = _redis_raw_get(_history_key(user_id))
        if raw is not None:
            return json.loads(raw) if raw else []
    except Exception as e:
        print(f"[Redis] load_history error: {e}")
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
        try:
            _redis_raw_set(_history_key(user_id), json.dumps(serializable, ensure_ascii=False))
            return
        except Exception as e:
            print(f"[Redis] save_history error: {e}")
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
        month = str(date.today())[:7]
        try:
            raw_shields = _redis_raw_get(f"shields:{user_id}:{month}")
            shield_dates = set(json.loads(raw_shields)) if raw_shields else set()
        except Exception:
            shield_dates = set()
        streak = 0
        check_date = date.today()
        while str(check_date) in meal_dates or str(check_date) in shield_dates:
            streak += 1
            check_date -= timedelta(days=1)

        # Calculate today's calories
        today_iso = str(date.today())
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
                referrer_uid = _redis_raw_get(f"code_to_uid:{ref_code}")
                if referrer_uid:
                    count = int(_redis_raw_get(f"referral_count:{referrer_uid}") or 0)
                    _redis_raw_set(f"referral_count:{referrer_uid}", str(count + 1))
            except Exception:
                pass
    return jsonify(result)

@app.route("/login", methods=["POST"])
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
        today_iso = str(date.today())

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

        # Weekly calories (last 7 days)
        weekly = []
        for i in range(6, -1, -1):
            d = str(date.today() - timedelta(days=i))
            day_meals = [m for m in progress.get("meal_log", []) if m.get("date") == d]
            kcal = sum(m.get("calories_estimate", 0) for m in day_meals)
            weekly.append({"date": d, "calories": kcal})

        # Water today
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
        from datetime import datetime as _dt
        hour = _dt.now().hour
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
        from datetime import date as _date, timedelta as _td
        cutoff = str(_date.today() - _td(days=7))
        recent_w = [l["weight_kg"] for l in logs if l.get("date","") >= cutoff]
        weekly_avg_weight = round(sum(recent_w)/len(recent_w), 1) if len(recent_w) >= 2 else None

        base.update({
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
    from datetime import date as _date
    month = str(_date.today())[:7]
    shield_key = f"shield_used:{uid}:{month}"
    if request.method == "GET":
        used = bool(_redis_raw_get(shield_key))
        return jsonify({"used": used, "month": month})
    # POST — activate shield for today
    if _redis_raw_get(shield_key):
        return jsonify({"ok": False, "msg": "כבר השתמשת במגן החודש הזה"})
    today = str(_date.today())
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

# ── Chat endpoint ────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401

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

        # Build user content
        if image_b64:
            if "," in image_b64:
                header, raw = image_b64.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
            else:
                raw, mime = image_b64, "image/jpeg"
            meal_id = "other"
            for m in ["breakfast", "snack", "lunch", "dinner"]:
                if m in user_text.lower():
                    meal_id = m
                    break
            hour = datetime.now().hour
            if meal_id == "other":
                if 6 <= hour < 10:    meal_id = "breakfast"
                elif 10 <= hour < 12: meal_id = "snack"
                elif 12 <= hour < 16: meal_id = "lunch"
                else:                 meal_id = "dinner"
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": raw}},
                {"type": "text",  "text": user_text or f"נתח את תמונת האוכל הזו וספור קלוריות. ארוחה: {meal_id}"}
            ]
        else:
            content = user_text

        conversation_history.append({"role": "user", "content": content})

        # Agentic loop (max 6 iterations)
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

        # If loop hit limit without finishing, add a graceful fallback message
        if not loop_completed and not text_parts:
            text_parts.append("✅ הפעולה בוצעה.")

        raw_text = "".join(text_parts) if text_parts else "✅ פעולה בוצעה!"
        final_text = _strip_markdown_tables(raw_text)

        # Extract weight for stats update
        weight_update = None
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        logs = progress.get("weight_log", [])
        if logs:
            weight_update = logs[-1]["weight_kg"]

        conversation_history = _safe_truncate(conversation_history, 40)
        save_history(uid, conversation_history)
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

    from datetime import date
    today = str(date.today())
    water_key = f"{uid}:water:{today}"

    if request.method == "POST":
        data = request.get_json()
        action = data.get("action", "add")  # "add" or "reset"
        current = int(_redis_raw_get(water_key) or 0)
        if action == "reset":
            new_val = 0
        else:
            new_val = current + 1
        _redis_raw_set(water_key, str(new_val))
        return jsonify({"glasses": new_val})
    else:
        glasses = int(_redis_raw_get(water_key) or 0)
        return jsonify({"glasses": glasses})

@app.route("/api/calorie-burn", methods=["GET", "POST"])
def api_calorie_burn():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    from datetime import date, timedelta
    today = str(date.today())
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
                    "time": __import__('datetime').datetime.now().strftime("%H:%M"),
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
        week_start = date.today() - timedelta(days=date.today().weekday())
        week_entries = [e for e in burn_log if e.get("date", "") >= str(week_start)]
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
                logs.append({"date": str(date.today()), "weight_kg": new_weight_f, "note": "עדכון פרופיל"})
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

        # Determine meal_id from caption or time of day
        from datetime import datetime as _dt
        hour = _dt.now().hour
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
        seven_days_ago = str(date.today() - timedelta(days=7))
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

        msg += "\nהמשך עם הסוכן: https://nutritionist-agent-ouvp.onrender.com/app"
        return msg
    finally:
        nutritionist._current_user_id = None


@app.route("/api/weekly-summary", methods=["POST"])
def weekly_summary():
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.environ.get("CRON_SECRET", "nutriai-cron-2026"):
        return jsonify({"error": "unauthorized"}), 401

    import urllib.request as ureq
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    # Scan for all account keys
    scan_req = ureq.Request(f"{url}/scan/0/match/account:*/count/100",
                            headers={"Authorization": f"Bearer {token}"})
    with ureq.urlopen(scan_req, timeout=5) as resp:
        keys = json.loads(resp.read())["result"][1]

    sent = 0
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

        seven_days_ago = str(date.today() - timedelta(days=7))
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
            report_date=str(date.today())
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
    referrals = int(_redis_raw_get(f"referral_count:{uid}") or 0)
    base_url = os.environ.get("APP_BASE_URL", "https://nutritionist-agent-ouvp.onrender.com")
    link = f"{base_url}/landing?ref={code}"
    return jsonify({"code": code, "link": link, "referrals": referrals})


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "service": "nutritionist-agent"}), 200


@app.route("/healthz")
def healthz():
    """Render health check endpoint"""
    return jsonify({"healthy": True}), 200

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
