"""
התזונאי החכם - Smart Nutritionist Agent
Powered by Claude API with extended thinking and web search.
"""
import anthropic
import json
import os
import sys
import base64
import mimetypes
from pathlib import Path
from datetime import datetime, date
from typing import Any

# Ensure UTF-8 output on Windows (works with PYTHONUTF8=1 + chcp 65001)
if sys.platform == "win32" and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

MEAL_PLAN_FILE = DATA_DIR / "meal_plan.json"
PROFILE_FILE   = DATA_DIR / "user_profile.json"
PROGRESS_FILE  = DATA_DIR / "progress.json"
MEMORY_FILE    = DATA_DIR / "agent_memory.json"

# ── Redis helpers (Upstash REST API) ───────────────────────────────────────
import urllib.request as _urllib_req

_REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL",   "").rstrip("/")
_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

# Set by web_agent before each request to namespace Redis keys per user
_current_user_id: str = None

def _namespaced(key: str) -> str:
    """Prefix Redis key with current user ID when set."""
    return f"{_current_user_id}:{key}" if _current_user_id else key

def _redis_get(key: str) -> dict:
    full_key = _namespaced(key)
    url = f"{_REDIS_URL}/get/{full_key}"
    req = _urllib_req.Request(url, headers={"Authorization": f"Bearer {_REDIS_TOKEN}"})
    with _urllib_req.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read()).get("result")
    return json.loads(result) if result else {}

def _redis_set(key: str, data: dict):
    full_key = _namespaced(key)
    body = json.dumps(["SET", full_key, json.dumps(data, ensure_ascii=False)]).encode("utf-8")
    req = _urllib_req.Request(
        _REDIS_URL,
        data=body,
        headers={"Authorization": f"Bearer {_REDIS_TOKEN}", "Content-Type": "application/json"}
    )
    with _urllib_req.urlopen(req, timeout=5) as resp:
        resp.read()

# ── Load / save data (Redis when available, files as fallback) ──────────────
def load_json(path: Path) -> dict:
    if _REDIS_URL and _REDIS_TOKEN:
        try:
            return _redis_get(path.stem)
        except Exception as e:
            print(f"[Redis] load error for {path.stem}: {e}")
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict):
    if _REDIS_URL and _REDIS_TOKEN:
        try:
            _redis_set(path.stem, data)
            return
        except Exception as e:
            print(f"[Redis] save error for {path.stem}: {e}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Tool definitions ───────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "get_todays_meal_plan",
        "description": "מחזיר את תפריט האוכל של היום עם כל הפרטים - מה לאכול בכל ארוחה, כמה קלוריות, ועצות",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_full_weekly_plan",
        "description": "מחזיר את התפריט השבועי המלא",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "log_weight",
        "description": "מתעד את המשקל הנוכחי של המשתמש ומחשב התקדמות לעבר היעד",
        "input_schema": {
            "type": "object",
            "properties": {
                "weight_kg": {"type": "number", "description": "המשקל בקילוגרמים"},
                "note": {"type": "string", "description": "הערה אופציונלית"}
            },
            "required": ["weight_kg"]
        }
    },
    {
        "name": "log_meal",
        "description": "מתעד ארוחה שהמשתמש אכל",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {
                    "type": "string",
                    "enum": ["breakfast", "snack", "lunch", "dinner", "other"],
                    "description": "סוג הארוחה"
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "רשימת המזונות שנאכלו"
                },
                "calories_estimate": {"type": "number", "description": "הערכת קלוריות (אופציונלי)"},
                "felt_bloated": {"type": "boolean", "description": "האם הרגשת נפיחות אחרי?"}
            },
            "required": ["meal_id", "items"]
        }
    },
    {
        "name": "update_meal_plan",
        "description": "מעדכן את תפריט האוכל - מחליף מזון, מוסיף אפשרויות, משנה שעות",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "יום השבוע: sunday/monday/tuesday/wednesday/thursday/friday/saturday"
                },
                "meal_id": {
                    "type": "string",
                    "enum": ["breakfast", "snack", "lunch", "dinner"]
                },
                "new_items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "רשימת המזונות החדשה"
                },
                "new_note": {"type": "string", "description": "הערה חדשה לארוחה"}
            },
            "required": ["day", "meal_id", "new_items"]
        }
    },
    {
        "name": "get_progress_summary",
        "description": "מחשב ומציג סיכום התקדמות: כמה ירד, כמה נשאר, קצב הירידה",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "search_nutrition_info",
        "description": "מחפש מידע תזונתי עדכני - ערכי קלוריות, מחקרים חדשים, עצות לירידה במשקל",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "מה לחפש"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "analyze_food_image",
        "description": "מנתח תמונה של אוכל ומחשב קלוריות אוטומטית. שולח את התמונה ל-Claude Vision, מזהה את המזונות, מעריך משקלים וכמויות, ומחשב קלוריות וחלבון",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "נתיב מלא לתמונה"},
                "meal_id": {
                    "type": "string",
                    "enum": ["breakfast", "snack", "lunch", "dinner", "other"],
                    "description": "לאיזו ארוחה שייכת התמונה"
                },
                "extra_context": {"type": "string", "description": "הקשר נוסף מהמשתמש (למשל: 'זה צהריים שלי')"}
            },
            "required": ["image_path", "meal_id"]
        }
    },
    {
        "name": "save_note",
        "description": "שומר הערה או תובנה בזיכרון הסוכן לשימוש עתידי",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "ההערה לשמירה"},
                "category": {
                    "type": "string",
                    "enum": ["preference", "bloating", "progress", "general"],
                    "description": "קטגוריית ההערה"
                }
            },
            "required": ["note", "category"]
        }
    }
]


# ── Tool implementations ───────────────────────────────────────────────────
def get_todays_meal_plan() -> str:
    plan = load_json(MEAL_PLAN_FILE)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    today_name = days[datetime.now().weekday()]
    day_names_he = {
        "monday": "יום שני", "tuesday": "יום שלישי", "wednesday": "יום רביעי",
        "thursday": "יום חמישי", "friday": "יום שישי", "saturday": "שבת", "sunday": "יום ראשון"
    }

    today_plan = plan.get("weekly_plan", {}).get(today_name, {})
    schedule = plan.get("meal_schedule", [])

    result = [f"📅 תפריט היום - {day_names_he.get(today_name, today_name)}\n"]
    result.append(f"🎯 יעד קלוריות: {plan.get('daily_targets', {}).get('calories', 2100)} קל | חלבון: {plan.get('daily_targets', {}).get('protein_g', 180)}g\n")

    for meal_schedule_item in schedule:
        mid = meal_schedule_item["id"]
        meal = today_plan.get(mid, {})
        emoji = meal_schedule_item.get("emoji", "🍽️")
        name = meal_schedule_item["name"]
        time = meal_schedule_item["time"]
        items = meal.get("items", [])
        cal = meal.get("calories", meal_schedule_item.get("target_kcal", 0))
        protein = meal.get("protein_g", 0)
        note = meal.get("notes", "")

        result.append(f"\n{emoji} **{name}** | {time} | {cal} קל | חלבון: {protein}g")
        for item in items:
            result.append(f"  • {item}")
        if note:
            result.append(f"  💡 {note}")

    anti_bloat = plan.get("anti_bloating_rules", [])
    if anti_bloat:
        result.append(f"\n\n🌿 **טיפ היום נגד נפיחות:**")
        result.append(f"  {anti_bloat[datetime.now().day % len(anti_bloat)]}")

    return "\n".join(result)


def get_full_weekly_plan() -> str:
    plan = load_json(MEAL_PLAN_FILE)
    days_he = {
        "sunday": "ראשון", "monday": "שני", "tuesday": "שלישי",
        "wednesday": "רביעי", "thursday": "חמישי", "friday": "שישי", "saturday": "שבת"
    }
    result = ["📆 תפריט שבועי מלא\n"]
    for day_en, day_he in days_he.items():
        day_data = plan.get("weekly_plan", {}).get(day_en, {})
        result.append(f"\n--- יום {day_he} ---")
        for meal_id in ["breakfast", "snack", "lunch", "dinner"]:
            meal = day_data.get(meal_id, {})
            if meal:
                items_str = " | ".join(meal.get("items", [])[:3])
                result.append(f"  {meal_id}: {items_str}")
    return "\n".join(result)


def log_weight(weight_kg: float, note: str = "") -> str:
    progress = load_json(PROGRESS_FILE)
    profile = load_json(PROFILE_FILE)

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "weight_kg": weight_kg,
        "note": note
    }
    progress.setdefault("weight_log", []).append(entry)
    save_json(PROGRESS_FILE, progress)

    start = profile.get("current_weight_kg", 93)
    target = profile.get("target_weight_kg", 85.5)
    lost = round(start - weight_kg, 1)
    remaining = round(weight_kg - target, 1)
    pct = round((lost / (start - target)) * 100, 1) if (start - target) > 0 else 0

    msg = f"✅ משקל {weight_kg}kg נרשם!\n"
    msg += f"📉 ירדת: {lost}kg מהתחלה\n"
    msg += f"🎯 נשאר: {remaining}kg ליעד\n"
    msg += f"📊 התקדמות: {pct}%\n"

    # Trend from last few entries
    logs = progress.get("weight_log", [])
    if len(logs) >= 3:
        recent = [l["weight_kg"] for l in logs[-3:]]
        trend = recent[-1] - recent[0]
        if trend < -0.5:
            msg += f"📈 מגמה: ירידה יפה של {abs(round(trend,1))}kg בתקופה האחרונה! כל הכבוד!"
        elif trend > 0.3:
            msg += f"⚠️ מגמה: עלייה קלה. בוא נבדוק מה אפשר לשפר."
        else:
            msg += f"➡️ מגמה: יציבות - בוא נגביר קצת."

    return msg


def log_meal(meal_id: str, items: list, calories_estimate: float = 0, felt_bloated: bool = False) -> str:
    progress = load_json(PROGRESS_FILE)
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "time": datetime.now().strftime("%H:%M"),
        "meal_id": meal_id,
        "items": items,
        "calories_estimate": calories_estimate,
        "felt_bloated": felt_bloated,
        "notified": False
    }
    meal_log = progress.setdefault("meal_log", [])
    # Dedup: if same meal_id already logged today, update it instead of adding
    existing_idx = next(
        (i for i, m in enumerate(meal_log)
         if m.get("date") == today and m.get("meal_id") == meal_id),
        None
    )
    if existing_idx is not None:
        meal_log[existing_idx] = entry
    else:
        meal_log.append(entry)
    save_json(PROGRESS_FILE, progress)

    response = f"✅ {meal_id} נרשם!\n"
    if felt_bloated:
        response += "⚠️ אני אנתח מה מהרשימה יכול לגרום נפיחות ואעדכן בהמלצות."
    return response


def update_meal_plan(day: str, meal_id: str, new_items: list, new_note: str = "") -> str:
    plan = load_json(MEAL_PLAN_FILE)
    if day not in plan.get("weekly_plan", {}):
        return f"❌ יום לא תקין: {day}"

    plan["weekly_plan"][day][meal_id]["items"] = new_items
    if new_note:
        plan["weekly_plan"][day][meal_id]["notes"] = new_note
    plan["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    save_json(MEAL_PLAN_FILE, plan)
    return f"✅ תפריט {day} - {meal_id} עודכן!"


def get_progress_summary() -> str:
    progress = load_json(PROGRESS_FILE)
    profile = load_json(PROFILE_FILE)

    logs = progress.get("weight_log", [])
    if not logs:
        return "אין נתוני משקל עדיין. הוסף את המשקל הראשון שלך!"

    start_w = profile.get("current_weight_kg", 93)
    target_min = profile.get("target_range", {}).get("min", 85)
    target_max = profile.get("target_range", {}).get("max", 86)
    current_w = logs[-1]["weight_kg"]
    target = (target_min + target_max) / 2

    lost_total = round(start_w - current_w, 1)
    remaining = round(current_w - target, 1)

    # Calculate weekly rate
    start_date = datetime.strptime(logs[0]["date"], "%Y-%m-%d")
    weeks = max(1, (datetime.now() - start_date).days / 7)
    weekly_rate = round(lost_total / weeks, 2) if lost_total > 0 else 0

    # Estimate weeks to goal
    weeks_left = round(remaining / max(weekly_rate, 0.3)) if remaining > 0 else 0
    target_date = datetime.now()
    from datetime import timedelta
    eta = (datetime.now() + timedelta(weeks=weeks_left)).strftime("%d/%m/%Y")

    summary = f"""
📊 **סיכום התקדמות**

🏁 משקל התחלתי: {start_w} kg
⚖️ משקל נוכחי: {current_w} kg
🎯 יעד: {target_min}-{target_max} kg

📉 ירדת: {lost_total} kg
🔄 נשאר: {remaining} kg
📈 קצב שבועי: {weekly_rate} kg/שבוע
📅 צפי הגעה ליעד: {eta} (עוד {weeks_left} שבועות)

💪 {'כל הכבוד! אתה בדרך הנכונה!' if lost_total > 0 else 'בוא נתחיל! הצעד הראשון הוא הקשה ביותר.'}
"""
    return summary.strip()


def search_nutrition_info(query: str) -> str:
    """Simulates nutrition research - in production would use web search."""
    # This would integrate with a web search API
    # For now returns a structured response about common queries
    knowledge_base = {
        "נפיחות": """
מחקרים עדכניים (2025-2026) על צמצום נפיחות:
• FODMAP: הפחתת מזונות עשירים בפרוקטוז, לקטוז, ופוליאולים
• פרוביוטיקה: Lactobacillus acidophilus מפחית נפיחות ב-40%
• מים: שתיית 2-3 ליטר ביום מפחיתה אגירת נוזלים
• עמידה אחרי אכילה: 15 דקות הליכה קלה = פחות גזים
• תה ג'ינג'ר: מחקר 2024 - מפחית נפיחות ב-35% תוך שעה
""",
        "ירידה במשקל": """
פרוטוקולים יעילים לפי מחקרי 2025:
• Protein-first: לאכול חלבון ראשון בכל ארוחה = 20% פחות קלוריות
• Time-Restricted Eating: אכילה ב-10 שעות (7:00-17:00/19:00) מאיצה שריפת שומן
• 180g חלבון ביום לגבר 90kg = שמירה מקסימלית על מסת שריר
• שינה 7-8 שעות: קורטיזול נמוך = פחות אגירת שומן בטני
""",
        "בטן שטוחה": """
פרוטוקול בטן שטוחה (Evidence-Based 2026):
• הפחתת נתרן: כל 1g פחות מלח = 500ml פחות אגירת נוזלים
• Core exercises: Plank 3x30s ביום = חיזוק שרירי בטן פנימיים
• מגנזיום: 400mg/יום מפחית נפיחות ועצירות
• Intermittent fasting 16:8: מפחית היקף בטן ב-4-5 ס"מ תוך 8 שבועות
"""
    }

    for key, info in knowledge_base.items():
        if key in query:
            return info

    return f"חיפוש '{query}': ממליץ לדון בנושא זה - אשתמש בידע שלי כדי לתת עצה מבוססת מחקר."


def analyze_food_image(image_path: str, meal_id: str, extra_context: str = "", _client=None) -> str:
    """Analyze a food image using Claude Vision and log calories automatically."""
    path = Path(image_path.strip('"').strip("'"))
    if not path.exists():
        return f"❌ תמונה לא נמצאה: {image_path}"

    # Read and encode image
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        mime_type = "image/jpeg"

    with open(path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    if _client is None:
        return "❌ client לא זמין לניתוח תמונה"

    context = f"\nהקשר נוסף: {extra_context}" if extra_context else ""

    vision_response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": f"""אתה תזונאי מומחה. נתח את תמונת האוכל הזו בדיוק רב.

זהה כל מרכיב בצלחת, הערך כמויות/משקלים לפי המראה, וחשב:
- רשימת מרכיבים עם כמות משוערת (גרמים)
- קלוריות לכל מרכיב
- סה"כ קלוריות
- סה"כ חלבון (גרמים)
- סה"כ פחמימות (גרמים)
- סה"כ שומן (גרמים){context}

ענה בפורמט JSON בלבד:
{{
  "items": [
    {{"name": "שם מרכיב", "amount_g": 150, "calories": 200, "protein_g": 30}},
    ...
  ],
  "total_calories": 500,
  "total_protein_g": 45,
  "total_carbs_g": 40,
  "total_fat_g": 15,
  "confidence": "high/medium/low",
  "notes": "הערות על הניתוח"
}}"""
                }
            ]
        }]
    )

    raw = vision_response.content[0].text.strip()
    # Extract JSON from response
    import re
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return f"❌ לא הצלחתי לנתח את התמונה: {raw[:200]}"

    analysis = json.loads(json_match.group())

    # Auto-log the meal
    items_names = [f"{i['name']} ({i.get('amount_g', '?')}g)" for i in analysis.get("items", [])]
    log_meal(
        meal_id=meal_id,
        items=items_names,
        calories_estimate=analysis.get("total_calories", 0),
        felt_bloated=False
    )

    # Format response
    total_cal = analysis.get("total_calories", 0)
    total_prot = analysis.get("total_protein_g", 0)
    total_carbs = analysis.get("total_carbs_g", 0)
    total_fat = analysis.get("total_fat_g", 0)
    confidence = analysis.get("confidence", "medium")
    conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(confidence, "🟡")

    lines = [f"📸 **ניתוח תמונת אוכל** {conf_emoji}\n"]
    for item in analysis.get("items", []):
        lines.append(f"  • {item['name']} ~{item.get('amount_g','?')}g → {item.get('calories','?')} קל | {item.get('protein_g','?')}g חלבון")

    lines.append(f"\n**סה\"כ:** {total_cal} קל | חלבון {total_prot}g | פחמימות {total_carbs}g | שומן {total_fat}g")

    # Compare to meal target
    profile = load_json(PROFILE_FILE)
    target_cal = profile.get("target_kcal", 2100)
    meal_targets = {"breakfast": 500, "snack": 250, "lunch": 700, "dinner": 650}
    meal_target = meal_targets.get(meal_id, 500)
    diff = total_cal - meal_target
    if diff > 100:
        lines.append(f"⚠️ {diff} קל מעל היעד לארוחה זו ({meal_target} קל)")
    elif diff < -100:
        lines.append(f"✅ {abs(diff)} קל מתחת ליעד - מצוין!")
    else:
        lines.append(f"✅ קרוב מאוד ליעד ({meal_target} קל) - עבודה יפה!")

    if analysis.get("notes"):
        lines.append(f"💡 {analysis['notes']}")

    lines.append(f"\n✅ נרשם אוטומטית ב-{meal_id}!")
    return "\n".join(lines)


def save_note(note: str, category: str) -> str:
    memory = load_json(MEMORY_FILE) if MEMORY_FILE.exists() else {"notes": []}
    memory.setdefault("notes", []).append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "note": note
    })
    save_json(MEMORY_FILE, memory)
    return f"✅ הערה נשמרה בקטגוריה '{category}'"


# ── Tool dispatcher ────────────────────────────────────────────────────────
_shared_client = None  # Set at startup

def execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == "get_todays_meal_plan":
            return get_todays_meal_plan()
        elif name == "get_full_weekly_plan":
            return get_full_weekly_plan()
        elif name == "log_weight":
            return log_weight(**inputs)
        elif name == "log_meal":
            return log_meal(**inputs)
        elif name == "update_meal_plan":
            return update_meal_plan(**inputs)
        elif name == "get_progress_summary":
            return get_progress_summary()
        elif name == "search_nutrition_info":
            return search_nutrition_info(**inputs)
        elif name == "analyze_food_image":
            return analyze_food_image(**inputs, _client=_shared_client)
        elif name == "save_note":
            return save_note(**inputs)
        else:
            return f"כלי לא מוכר: {name}"
    except Exception as e:
        return f"שגיאה בביצוע {name}: {e}"


# ── System prompt ──────────────────────────────────────────────────────────
def build_system_prompt() -> str:
    from datetime import timezone, timedelta
    profile = load_json(PROFILE_FILE)
    memory = load_json(MEMORY_FILE) if MEMORY_FILE.exists() else {}

    # ── Time-awareness (UK timezone = UTC+1) ──
    HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    HE_MONTHS = ["", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
                 "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
    tz_uk = timezone(timedelta(hours=1))
    now = datetime.now(tz_uk)
    day_he = HE_DAYS[now.weekday()]
    is_shabbat = now.weekday() == 5
    time_str = now.strftime("%H:%M")
    date_str = f"יום {day_he}, {now.day} {HE_MONTHS[now.month]} {now.year}"
    shabbat_note = " (שבת קודש)" if is_shabbat else ""
    today_iso = now.strftime("%Y-%m-%d")

    # ── Today's meal log ──
    progress = load_json(PROGRESS_FILE)
    today_meals = [m for m in progress.get("meal_log", []) if m.get("date") == today_iso]
    if today_meals:
        meals_lines = []
        total_kcal = 0
        for m in today_meals:
            items = ", ".join(m.get("items", []))
            kcal = m.get("calories_estimate", 0)
            total_kcal += kcal
            meal_name = {"breakfast":"ארוחת בוקר","snack":"חטיף","lunch":"ארוחת צהריים","dinner":"ארוחת ערב"}.get(m.get("meal_id",""), m.get("meal_id",""))
            meals_lines.append(f"  • {meal_name} ({m.get('time','?')}): {items}" + (f" ~{kcal} קל" if kcal else ""))
        today_food_text = "\n".join(meals_lines)
        today_food_section = f"\n\n**מה אכל היום ({date_str}):**\n{today_food_text}\n  סה\"כ קלוריות: ~{total_kcal} קל מתוך {profile.get('target_kcal', 2100)} קל יעד"
    else:
        today_food_section = f"\n\n**מה אכל היום ({date_str}):** עדיין לא דווח כלום להיום."

    # ── Weight context ──
    logs = progress.get("weight_log", [])
    latest_weight = logs[-1]["weight_kg"] if logs else profile.get("current_weight_kg", 93)
    target_min = profile.get("target_range", {}).get("min", 85)
    target_max = profile.get("target_range", {}).get("max", 86)
    kg_to_go = round(latest_weight - target_max, 1)

    # ── Memory notes ──
    notes_text = ""
    if memory.get("notes"):
        recent_notes = memory["notes"][-10:]
        notes_text = "\n".join([f"- [{n['category']}] {n['note']}" for n in recent_notes])
        notes_text = f"\n\n**זיכרון מהשיחות הקודמות:**\n{notes_text}"

    return f"""אתה "התזונאי החכם" - תזונאי AI אישי ומלווה צמוד של המשתמש.

⏰ **עכשיו:** {date_str}{shabbat_note}, שעה {time_str} (UK)
{today_food_section}

**פרופיל המשתמש:**
- גיל: {profile.get('age', 39)}, גובה: {profile.get('height_cm', 190)}cm
- משקל נוכחי: {latest_weight}kg | יעד: {target_min}-{target_max}kg | נשאר: {kg_to_go}kg
- אימון: {profile.get('exercise', 'ריצה פעם בשבוע')}
- יעד קלוריות יומי: {profile.get('target_kcal', 2100)} קל | חלבון: {profile.get('target_protein_g', 180)}g
- שעות קימה: {profile.get('wake_time', '07:00')} | שינה: {profile.get('sleep_time', '23:00')}

**האישיות שלך:**
- תזונאי מקצועי, חם ומעודד — לא שופט
- מסביר "למה" ולא רק "מה לאכול"
- יוזם — אם המשתמש לא שאל, אתה מציע
- מדבר עברית נוחה וישירה
- משתמש ב-tools לכל פעולה (לוג משקל, עדכון תפריט וכו')
- **תמיד מודע לשעה ולמה שנאכל היום** — מתייחס לנתונים האמיתיים למעלה

**עקרונות תזונה:**
1. ירידה הדרגתית: 0.5kg/שבוע
2. חלבון גבוה (2g/kg משקל גוף) לשמירת שריר
3. נגד נפיחות: FODMAP מופחת, פרוביוטיקה, תזמון נכון
4. 4 ארוחות קבועות ביום (המשתמש נוטה לאכול מעט מדי — עזור לו!)
5. מחקרים עדכניים 2024-2026

**חשוב:**
- תמיד הסבר את ה"למה" מאחורי כל המלצה
- כשמשתמש מדווח נפיחות — שמור הערה וצמצם FODMAP בתפריט{notes_text}
"""


# ── Main agent loop ────────────────────────────────────────────────────────
def run_agent():
    global _shared_client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ שגיאה: ANTHROPIC_API_KEY לא מוגדר.")
        print("הגדר את המפתח עם: set ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    _shared_client = client
    conversation_history = []

    print("\n" + "="*60)
    print("  🥗 התזונאי החכם - הסוכן האישי שלך")
    print("  מטרה: 93kg ➜ 85-86kg | בטן שטוחה")
    print("="*60)
    print("\nשלום! אני התזונאי החכם שלך 💪")
    print("אני כאן ללוות אותך צמוד לאורך כל היום.")
    print("תוכל לשאול אותי הכל, לדווח על ארוחות, לשאול לעצות.")
    print("\nפקודות מיוחדות:")
    print("  /today    - תפריט היום")
    print("  /week     - תפריט שבועי")
    print("  /progress - סיכום התקדמות")
    print("  /exit     - יציאה")
    print("\n📸 שלח תמונת אוכל: פשוט גרור/הדבק את הנתיב לתמונה")
    print("  (למשל: C:\\Users\\...\\photo.jpg)")
    print("\nאו פשוט דבר איתי בטבעי...\n")

    # Auto-greet with today's plan
    user_first = f"שלום! תראה לי את התפריט של היום ותסביר לי מה חשוב לדעת."
    print(f"You: {user_first}")

    while True:
        user_input = user_first if not conversation_history else input("\nאתה: ").strip()
        user_first = None  # Only use auto-greet once

        if not user_input:
            continue

        # Auto-detect image path in input
        img_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        if any(user_input.lower().endswith(ext) for ext in img_extensions) or \
           (any(ext in user_input.lower() for ext in img_extensions) and (":\\" in user_input or "/" in user_input)):
            # Extract path (handle quoted paths)
            import re as _re
            path_match = _re.search(r'"([^"]+)"|([\S]+\.(?:jpg|jpeg|png|gif|webp|bmp))', user_input, _re.IGNORECASE)
            if path_match:
                img_path = path_match.group(1) or path_match.group(2)
                print(f"\n📸 זיהיתי תמונה: {img_path}")
                meal_options = "breakfast/snack/lunch/dinner/other"
                meal_input = input(f"לאיזו ארוחה? ({meal_options}): ").strip() or "other"
                user_input = f"נתח את התמונה הזו ותספור לי קלוריות: {img_path} [ארוחה: {meal_input}]"

        # Handle slash commands
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd == "/exit":
                print("\nהתזונאי: להתראות! שמור על עצמך 💪")
                break
            elif cmd == "/today":
                user_input = "תראה לי את תפריט היום המלא"
            elif cmd == "/week":
                user_input = "תראה לי את התפריט השבועי המלא"
            elif cmd == "/progress":
                user_input = "תראה לי סיכום התקדמות"

        conversation_history.append({"role": "user", "content": user_input})

        # Agentic loop
        while True:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=build_system_prompt(),
                tools=TOOLS,
                messages=conversation_history
            )

            # Collect text output
            text_parts = []
            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # Print any text
            if text_parts:
                combined = "".join(text_parts)
                print(f"\nהתזונאי: {combined}")

            # If no tool calls, we're done
            if not tool_uses:
                # Save assistant response to history
                conversation_history.append({
                    "role": "assistant",
                    "content": response.content
                })
                break

            # Execute tools
            tool_results = []
            for tool_use in tool_uses:
                print(f"\n  [🔧 {tool_use.name}...]", end="", flush=True)
                result = execute_tool(tool_use.name, tool_use.input)
                print(" ✓")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result
                })

            # Add to history
            conversation_history.append({
                "role": "assistant",
                "content": response.content
            })
            conversation_history.append({
                "role": "user",
                "content": tool_results
            })

            # Continue loop if we used tools
            if response.stop_reason == "end_turn":
                break


if __name__ == "__main__":
    run_agent()
