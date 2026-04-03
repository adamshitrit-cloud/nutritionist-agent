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

def register_user(name: str, email: str, password: str, lang: str = "he") -> dict:
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
        "created_at": datetime.now().isoformat()
    }
    _save_user(user)
    return {"ok": True, "user_id": user["id"], "name": user["name"], "lang": lang}

def login_user(email: str, password: str) -> dict:
    """Returns {'ok': True, 'user_id': ...} or {'error': '...'}"""
    user = _get_user_by_email(email.lower().strip())
    if not user:
        return {"error": "המייל לא נמצא" }
    if _hash_password(password, user["salt"]) != user["password_hash"]:
        return {"error": "סיסמה שגויה"}
    return {"ok": True, "user_id": user["id"], "name": user["name"], "lang": user.get("lang", "he")}

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
        start_w   = profile.get("current_weight_kg", None)
        target_min = profile.get("target_range", {}).get("min", None)
        target_max = profile.get("target_range", {}).get("max", None)
        return {
            "current_weight": current_w,
            "start_weight": start_w,
            "target_min": target_min,
            "target_max": target_max,
            "lost": round(start_w - current_w, 1) if (start_w and current_w) else None,
            "weight_log": logs[-20:],  # last 20 entries
            "name": profile.get("name", "")
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
    return redirect(url_for("landing"))

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
        lang=data.get("lang", "he")
    )
    if result.get("ok"):
        session["user_id"] = result["user_id"]
        session["name"]    = result["name"]
        session["lang"]    = result["lang"]
    return jsonify(result)

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    result = login_user(data.get("email", ""), data.get("password", ""))
    if result.get("ok"):
        session["user_id"] = result["user_id"]
        session["name"]    = result["name"]
        session["lang"]    = result.get("lang", "he")
    return jsonify(result)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

@app.route("/api/stats")
def api_stats():
    uid = current_user_id()
    if not uid:
        return jsonify({"error": "not logged in"}), 401
    return jsonify(get_user_stats(uid))

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

        # Agentic loop
        text_parts = []
        for _ in range(6):
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
                break

        final_text = "".join(text_parts) if text_parts else "✅ פעולה בוצעה!"

        # Extract weight for stats update
        weight_update = None
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        logs = progress.get("weight_log", [])
        if logs:
            weight_update = logs[-1]["weight_kg"]

        if len(conversation_history) > 40:
            conversation_history = conversation_history[-40:]

        save_history(uid, conversation_history)
        return jsonify({"response": final_text, "weight": weight_update})

    except Exception as e:
        import traceback; traceback.print_exc()
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
    """Convert 'whatsapp:+972501234567' → '972501234567'."""
    return re.sub(r'\D', '', from_number)

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

        response = nutritionist._shared_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text",  "text": prompt}
            ]}]
        )
        reply = response.content[0].text
        history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        if len(history) > 40:
            history = history[-40:]
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

        if len(history) > 40:
            history = history[-40:]
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

@app.route("/ping")
def ping():
    return "ok", 200

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
