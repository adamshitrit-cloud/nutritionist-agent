"""
Flask web server for the Smart Nutritionist Agent.
Serves the RTL Hebrew chat interface and connects to Claude API.
"""
from flask import Flask, render_template, request, jsonify, Response
import anthropic
import json
import os
import sys
import base64
import re
from pathlib import Path
from datetime import datetime

# ── Import agent tools ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
import agent as nutritionist

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "conversation_history.json"

app = Flask(__name__, template_folder="templates")

# Global state
client = None


def _redis_get_history() -> list:
    url   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    import urllib.request
    req = urllib.request.Request(f"{url}/get/conversation_history",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read()).get("result")
    return json.loads(result) if result else []

def _redis_set_history(history: list):
    url   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return
    import urllib.request
    body = json.dumps(["SET", "conversation_history",
                       json.dumps(history, ensure_ascii=False)]).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()

def load_history() -> list:
    try:
        result = _redis_get_history()
        if result is not None:
            return result
    except Exception as e:
        print(f"[Redis] load_history error: {e}")
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _serialize_content(content):
    """Convert Anthropic SDK content blocks to plain JSON-serializable dicts."""
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


def save_history(history: list):
    try:
        serializable = [
            {"role": m["role"], "content": _serialize_content(m["content"])}
            for m in history
        ]
        try:
            _redis_set_history(serializable)
            return
        except Exception as e:
            print(f"[Redis] save_history error: {e}")
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


conversation_history = load_history()


def get_client():
    global client
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        nutritionist._shared_client = client
    return client


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    global conversation_history

    data = request.get_json()
    user_text = data.get("message", "").strip()
    image_b64 = data.get("image")       # data:image/jpeg;base64,...
    image_name = data.get("image_name", "food.jpg")

    if not user_text and not image_b64:
        return jsonify({"error": "הודעה ריקה"}), 400

    try:
        cl = get_client()

        # Build user content
        if image_b64:
            # Strip data URL prefix → raw base64
            if "," in image_b64:
                header, raw = image_b64.split(",", 1)
                mime = header.split(":")[1].split(";")[0]  # e.g. image/jpeg
            else:
                raw, mime = image_b64, "image/jpeg"

            # Determine meal context from text
            meal_id = "other"
            for m in ["breakfast", "snack", "lunch", "dinner"]:
                if m in user_text.lower():
                    meal_id = m
                    break
            hour = datetime.now().hour
            if meal_id == "other":
                if 6 <= hour < 10:   meal_id = "breakfast"
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
        max_iterations = 6
        for _ in range(max_iterations):
            response = cl.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=nutritionist.build_system_prompt(),
                tools=nutritionist.TOOLS,
                messages=conversation_history
            )

            text_parts = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                conversation_history.append({"role": "assistant", "content": response.content})
                break

            # Execute tools
            tool_results = []
            for tu in tool_uses:
                inputs = dict(tu.input)
                # For image tool called via Claude, pass client
                if tu.name == "analyze_food_image":
                    inputs["_client"] = cl
                result = nutritionist.execute_tool(tu.name, inputs)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result
                })

            conversation_history.append({"role": "assistant", "content": response.content})
            conversation_history.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                break

        final_text = "".join(text_parts) if text_parts else "✅ פעולה בוצעה!"

        # Extract current weight for stats update
        weight_update = None
        progress = nutritionist.load_json(nutritionist.PROGRESS_FILE)
        logs = progress.get("weight_log", [])
        if logs:
            weight_update = logs[-1]["weight_kg"]

        # Keep conversation manageable (last 20 turns)
        if len(conversation_history) > 40:
            conversation_history = conversation_history[-40:]

        save_history(conversation_history)
        return jsonify({"response": final_text, "weight": weight_update})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/reset", methods=["POST"])
def reset():
    global conversation_history
    conversation_history = []
    save_history(conversation_history)
    return jsonify({"ok": True})


# ── WhatsApp conversations (shared history with web UI) ────────────────────

def process_whatsapp_image(phone: str, media_url: str, caption: str) -> str:
    """Download image from Twilio and analyze calories via Claude Vision."""
    import urllib.request, urllib.error
    try:
        # Twilio requires auth to download media
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "")

        if account_sid and auth_token:
            import urllib.request
            password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, media_url, account_sid, auth_token)
            handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
            opener  = urllib.request.build_opener(handler)
            with opener.open(media_url, timeout=15) as resp:
                image_data = resp.read()
        else:
            # Try without auth (sandbox may allow it)
            import urllib.request
            with urllib.request.urlopen(media_url, timeout=15) as resp:
                image_data = resp.read()

        # Encode and send to Claude Vision
        image_b64 = base64.b64encode(image_data).decode("utf-8")
        prompt = caption if caption else "נתח את האוכל בתמונה וספר לי: מה יש כאן? כמה קלוריות בערך? כמה חלבון?"

        global conversation_history
        conversation_history.append({"role": "user", "content": f"[WhatsApp תמונה] {prompt}"})

        response = nutritionist._shared_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text",  "text": prompt}
                ]
            }]
        )
        reply = response.content[0].text
        conversation_history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        if len(conversation_history) > 40:
            conversation_history = conversation_history[-40:]
        save_history(conversation_history)
        return reply

    except Exception as e:
        return f"לא הצלחתי לקרוא את התמונה: {e}"


def process_for_whatsapp(phone: str, user_text: str) -> str:
    """Run agent for a WhatsApp user and return plain-text response."""
    global conversation_history
    history = conversation_history
    history.append({"role": "user", "content": f"[WhatsApp] {user_text}"})

    cl = get_client()
    text_parts = []

    for _ in range(6):
        response = cl.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,   # shorter for WhatsApp
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

    # Keep history manageable
    if len(history) > 40:
        conversation_history = history[-40:]
    save_history(conversation_history)

    reply = "".join(text_parts) if text_parts else "✅ בוצע!"
    # Strip markdown for WhatsApp (plain text)
    reply = re.sub(r'\*\*(.+?)\*\*', r'*\1*', reply)   # bold → WhatsApp bold
    reply = re.sub(r'#{1,3} (.+)', r'*\1*', reply)      # headers → bold
    return reply


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Twilio WhatsApp webhook endpoint."""
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number  = request.values.get("From", "unknown")
        num_media    = int(request.values.get("NumMedia", "0"))

        print(f"[WhatsApp] From: {from_number} | Msg: {incoming_msg[:60]} | Media: {num_media}")

        # Handle image sent from WhatsApp
        if num_media > 0:
            media_url         = request.values.get("MediaUrl0", "")
            media_content_type = request.values.get("MediaContentType0", "")
            if media_url and "image" in media_content_type:
                reply = process_whatsapp_image(from_number, media_url, incoming_msg)
                return _twilio_reply(reply)

        if not incoming_msg:
            return _twilio_reply("שלום! שלח לי הודעה ואשמח לעזור 🥗")

        reply = process_for_whatsapp(from_number, incoming_msg)
        return _twilio_reply(reply)

    except Exception as e:
        import traceback; traceback.print_exc()
        return _twilio_reply(f"שגיאה: {e}")


def _twilio_reply(text: str) -> Response:
    """Return a Twilio TwiML response."""
    # Escape XML special chars
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{text}</Message>
</Response>"""
    return Response(xml, mimetype="text/xml")


if __name__ == "__main__":
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    print("=" * 50)
    print("  Smart Nutritionist Agent - Web UI")
    print("  http://localhost:5000")
    print("=" * 50)

    import webbrowser, threading
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()

    # Listen on all interfaces so ngrok can tunnel to it
    app.run(host="0.0.0.0", port=5000, debug=False)
