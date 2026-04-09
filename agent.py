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

def _redis_raw_get(full_key: str) -> str | None:
    """Get a raw string value from Redis (not JSON-wrapped). full_key is NOT namespaced."""
    url = f"{_REDIS_URL}/get/{full_key}"
    req = _urllib_req.Request(url, headers={"Authorization": f"Bearer {_REDIS_TOKEN}"})
    with _urllib_req.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read()).get("result")
    return result  # plain string or None

def _redis_raw_set(full_key: str, value: str):
    """Set a raw string value in Redis (not JSON-wrapped). full_key is NOT namespaced."""
    body = json.dumps(["SET", full_key, value]).encode("utf-8")
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
                "protein_g": {"type": "number", "description": "גרמי חלבון (אופציונלי) — חשוב! תמיד נסה להעריך"},
                "carbs_g":   {"type": "number", "description": "גרמי פחמימות (אופציונלי)"},
                "fat_g":     {"type": "number", "description": "גרמי שומן (אופציונלי)"},
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
        "description": "שומר הערה, טיפ, או תובנה בזיכרון הסוכן — מוצגות בדשבורד. השתמש ב-tip לטיפים, insight לתובנות, weekly לסיכום שבועי, bloating לנפיחות, preference להעדפות, progress להתקדמות",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "ההערה לשמירה"},
                "category": {
                    "type": "string",
                    "enum": ["tip", "insight", "weekly", "bloating", "preference", "progress", "general"],
                    "description": "קטגוריית ההערה: tip=טיפ, insight=תובנה, weekly=שבועי, bloating=נפיחות, preference=העדפה, progress=התקדמות"
                }
            },
            "required": ["note", "category"]
        }
    },
    {
        "name": "delete_meal",
        "description": "מוחק רישום ארוחה של היום — להשתמש כשהמשתמש אומר 'טעות', 'לא אכלתי את זה', 'מחק את הארוחה', 'בטל לוג'",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {
                    "type": "string",
                    "enum": ["breakfast", "snack", "lunch", "dinner", "other"],
                    "description": "סוג הארוחה למחיקה"
                }
            },
            "required": ["meal_id"]
        }
    },
    {
        "name": "log_exercise",
        "description": "מתעד פעילות גופנית ושריפת קלוריות. קרא כשהמשתמש מדווח על ריצה, הליכה, חדר כושר, שחייה, אופניים, יוגה וכו'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string", "description": "סוג הפעילות (למשל: ריצה, הליכה, חדר כושר, שחייה)"},
                "duration_min": {"type": "integer", "description": "משך הפעילות בדקות"},
                "calories": {"type": "integer", "description": "הערכת קלוריות שנשרפו"}
            },
            "required": ["activity", "duration_min", "calories"]
        }
    },
    {
        "name": "log_water",
        "description": "מתעד שתיית מים. קרא לזה בכל פעם שהמשתמש אומר 'שתיתי מים', 'כוס מים', 'שתיתי' וכדומה. מגדיל את מונה המים היומי.",
        "input_schema": {
            "type": "object",
            "properties": {
                "glasses": {
                    "type": "integer",
                    "description": "מספר כוסות מים שנשתו (ברירת מחדל: 1)",
                    "default": 1
                }
            },
            "required": []
        }
    },
    {
        "name": "log_measurement",
        "description": "מתעד מדידות גוף (היקף מותניים, חזה, ירכיים)",
        "input_schema": {
            "type": "object",
            "properties": {
                "waist_cm": {"type": "number", "description": "היקף מותניים בסנטימטרים"},
                "chest_cm": {"type": "number", "description": "היקף חזה בסנטימטרים"},
                "hips_cm": {"type": "number", "description": "היקף ירכיים בסנטימטרים"}
            },
            "required": []
        }
    }
]


# ── Tool implementations ───────────────────────────────────────────────────
def get_todays_meal_plan() -> str:
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    plan = load_json(MEAL_PLAN_FILE)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    today_name = days[datetime.now(tz_uk).weekday()]
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
        result.append(f"  {anti_bloat[datetime.now(tz_uk).day % len(anti_bloat)]}")

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
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    progress = load_json(PROGRESS_FILE)
    profile = load_json(PROFILE_FILE)

    entry = {
        "date": datetime.now(tz_uk).strftime("%Y-%m-%d"),
        "weight_kg": weight_kg,
        "note": note
    }
    progress.setdefault("weight_log", []).append(entry)
    save_json(PROGRESS_FILE, progress)

    # Keep profile.current_weight_kg in sync with latest logged weight
    profile["current_weight_kg"] = weight_kg
    save_json(PROFILE_FILE, profile)

    logs_all = progress.get("weight_log", [])
    start = logs_all[0]["weight_kg"] if len(logs_all) > 1 else profile.get("current_weight_kg", weight_kg)
    target = profile.get("target_range", {}).get("max") or profile.get("target_weight_kg") or (weight_kg - 5)
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


def log_meal(meal_id: str, items: list, calories_estimate: float = 0,
             protein_g: float = 0, carbs_g: float = 0, fat_g: float = 0,
             felt_bloated: bool = False) -> str:
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    _now = datetime.now(tz_uk)
    progress = load_json(PROGRESS_FILE)
    today = _now.strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "time": _now.strftime("%H:%M"),
        "meal_id": meal_id,
        "items": items,
        "calories_estimate": calories_estimate,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "felt_bloated": felt_bloated,
        "notified": False
    }
    meal_log = progress.setdefault("meal_log", [])
    # Accumulate: if same meal_id already logged today, merge items and sum macros
    existing_idx = next(
        (i for i, m in enumerate(meal_log)
         if m.get("date") == today and m.get("meal_id") == meal_id),
        None
    )
    if existing_idx is not None:
        ex = meal_log[existing_idx]
        # Merge item lists (preserve order, avoid exact duplicates)
        merged_items = list(ex.get("items", []))
        for item in items:
            if item not in merged_items:
                merged_items.append(item)
        entry["items"] = merged_items
        # Sum nutritional values
        entry["calories_estimate"] = (ex.get("calories_estimate") or 0) + calories_estimate
        entry["protein_g"]         = (ex.get("protein_g")         or 0) + protein_g
        entry["carbs_g"]           = (ex.get("carbs_g")           or 0) + carbs_g
        entry["fat_g"]             = (ex.get("fat_g")             or 0) + fat_g
        entry["felt_bloated"]      = ex.get("felt_bloated", False) or felt_bloated
        meal_log[existing_idx] = entry
    else:
        meal_log.append(entry)
    save_json(PROGRESS_FILE, progress)

    response = f"✅ {meal_id} נרשם!\n"
    if felt_bloated:
        response += "⚠️ אני אנתח מה מהרשימה יכול לגרום נפיחות ואעדכן בהמלצות."
    return response


def delete_meal(meal_id: str) -> str:
    progress = load_json(PROGRESS_FILE)
    today = datetime.now().strftime("%Y-%m-%d")
    meal_log = progress.get("meal_log", [])
    before = len(meal_log)
    progress["meal_log"] = [
        m for m in meal_log
        if not (m.get("date") == today and m.get("meal_id") == meal_id)
    ]
    after = len(progress["meal_log"])
    if before == after:
        return f"לא נמצאה ארוחת {meal_id} מהיום לביטול."
    save_json(PROGRESS_FILE, progress)
    return f"✅ ארוחת {meal_id} הוסרה מהרישום — הקלוריות עודכנו."


def update_meal_plan(day: str, meal_id: str, new_items: list, new_note: str = "") -> str:
    plan = load_json(MEAL_PLAN_FILE)
    if day not in plan.get("weekly_plan", {}):
        return f"❌ יום לא תקין: {day}"

    plan["weekly_plan"].setdefault(day, {}).setdefault(meal_id, {"items": [], "calories": 0, "protein_g": 0, "notes": ""})
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

    current_w = logs[-1]["weight_kg"]
    start_w = logs[0]["weight_kg"] if len(logs) >= 1 else profile.get("current_weight_kg", current_w)
    target_min = profile.get("target_range", {}).get("min") or profile.get("target_weight_kg")
    target_max = profile.get("target_range", {}).get("max") or target_min
    target = (((target_min or current_w) + (target_max or current_w)) / 2)

    lost_total = round(start_w - current_w, 1)
    remaining = round(current_w - target, 1)

    # Calculate weekly rate
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    start_date = datetime.strptime(logs[0]["date"], "%Y-%m-%d")
    weeks = max(1, (datetime.now(tz_uk).replace(tzinfo=None) - start_date).days / 7)
    weekly_rate = round(lost_total / weeks, 2) if lost_total > 0 else 0

    # Estimate weeks to goal
    weeks_left = round(remaining / max(weekly_rate, 0.3)) if remaining > 0 else 0
    eta = (datetime.now(tz_uk) + timedelta(weeks=weeks_left)).strftime("%d/%m/%Y")

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

    # Auto-log the meal including macros
    items_names = [f"{i['name']} ({i.get('amount_g', '?')}g)" for i in analysis.get("items", [])]
    log_meal(
        meal_id=meal_id,
        items=items_names,
        calories_estimate=analysis.get("total_calories", 0),
        protein_g=analysis.get("total_protein_g", 0),
        carbs_g=analysis.get("total_carbs_g", 0),
        fat_g=analysis.get("total_fat_g", 0),
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
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    # Always use load_json — uses Redis when available, never bypasses with .exists() check
    memory = load_json(MEMORY_FILE) or {}
    memory.setdefault("notes", []).append({
        "date": datetime.now(tz_uk).strftime("%Y-%m-%d"),
        "category": category,
        "note": note
    })
    save_json(MEMORY_FILE, memory)
    return f"✅ הערה נשמרה בקטגוריה '{category}'"


def log_exercise(activity: str, duration_min: int, calories: int) -> str:
    """Log a physical activity and calorie burn to progress data."""
    import uuid as _uuid
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    today_iso = datetime.now(tz_uk).strftime("%Y-%m-%d")
    time_str = datetime.now(tz_uk).strftime("%H:%M")
    progress = load_json(PROGRESS_FILE)
    burn_log = progress.setdefault("burn_log", [])
    entry = {
        "id": str(_uuid.uuid4())[:8],
        "date": today_iso,
        "time": time_str,
        "activity": activity,
        "calories": max(0, int(calories)),
        "duration_min": max(0, int(duration_min))
    }
    burn_log.append(entry)
    save_json(PROGRESS_FILE, progress)
    today_burn = sum(e["calories"] for e in burn_log if e.get("date") == today_iso)
    return f"✅ {activity} {duration_min} דק' — {calories} קל נשרפו | סה\"כ היום: {today_burn} קל"


def log_water(glasses: int = 1) -> str:
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    today_iso = datetime.now(tz_uk).strftime("%Y-%m-%d")
    glasses = max(1, min(int(glasses), 20))  # cap between 1–20
    if _REDIS_URL and _REDIS_TOKEN and _current_user_id:
        try:
            water_key = f"{_current_user_id}:water:{today_iso}"
            current_raw = _redis_raw_get(water_key)
            current = int(current_raw) if current_raw else 0
            new_val = min(current + glasses, 20)  # cap total at 20
            _redis_raw_set(water_key, str(new_val))
            return f"✅ {glasses} כוס מים נרשמה — סה\"כ היום: {new_val} כוסות"
        except Exception as e:
            return f"❌ שגיאה בשמירת מים: {e}"
    else:
        # Fallback: store in progress JSON
        progress = load_json(PROGRESS_FILE)
        water_log = progress.setdefault("water_log", {})
        current = water_log.get(today_iso, 0)
        new_val = min(current + glasses, 20)
        water_log[today_iso] = new_val
        save_json(PROGRESS_FILE, progress)
        return f"✅ {glasses} כוס מים נרשמה — סה\"כ היום: {new_val} כוסות"


def log_measurement(waist_cm: float = None, chest_cm: float = None, hips_cm: float = None) -> str:
    from datetime import timezone, timedelta
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    _now = datetime.now(tz_uk)
    progress = load_json(PROGRESS_FILE)
    entry = {
        "date": _now.strftime("%Y-%m-%d"),
        "time": _now.strftime("%H:%M")
    }
    if waist_cm: entry["waist_cm"] = waist_cm
    if chest_cm: entry["chest_cm"] = chest_cm
    if hips_cm: entry["hips_cm"] = hips_cm

    progress.setdefault("measurement_log", []).append(entry)
    save_json(PROGRESS_FILE, progress)

    parts = []
    if waist_cm: parts.append(f"מותניים: {waist_cm}ס\"מ")
    if chest_cm: parts.append(f"חזה: {chest_cm}ס\"מ")
    if hips_cm: parts.append(f"ירכיים: {hips_cm}ס\"מ")

    return f"✅ מדידות נרשמו: {', '.join(parts)}"


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
        elif name == "delete_meal":
            return delete_meal(**inputs)
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
        elif name == "log_water":
            return log_water(**inputs)
        elif name == "log_exercise":
            return log_exercise(**inputs)
        elif name == "log_measurement":
            return log_measurement(**inputs)
        else:
            return f"כלי לא מוכר: {name}"
    except Exception as e:
        return f"שגיאה בביצוע {name}: {e}"


# ── System prompt ──────────────────────────────────────────────────────────
def build_system_prompt() -> str:
    from datetime import timezone, timedelta
    profile = load_json(PROFILE_FILE)
    memory = load_json(MEMORY_FILE) or {}  # Always use Redis — never bypass with .exists()

    # ── Time-awareness (UK timezone = UTC+1) ──
    HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    HE_MONTHS = ["", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
                 "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
    tz_uk = timezone(timedelta(hours=2))  # Israel / UTC+2
    now = datetime.now(tz_uk)
    day_he = HE_DAYS[now.weekday()]
    is_shabbat = now.weekday() == 5
    time_str = now.strftime("%H:%M")
    date_str = f"יום {day_he}, {now.day} {HE_MONTHS[now.month]} {now.year}"
    shabbat_note = " (שבת קודש)" if is_shabbat else ""
    today_iso = now.strftime("%Y-%m-%d")

    # ── Today's meal log + water ──
    progress = load_json(PROGRESS_FILE)
    today_meals = [m for m in progress.get("meal_log", []) if m.get("date") == today_iso]
    # Water from Redis (same key the dashboard reads)
    water_today = 0
    if _REDIS_URL and _REDIS_TOKEN and _current_user_id:
        try:
            _w_raw = _redis_raw_get(f"{_current_user_id}:water:{today_iso}")
            water_today = int(_w_raw) if _w_raw else 0
        except Exception:
            water_today = 0
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
    latest_weight = logs[-1]["weight_kg"] if logs else profile.get("current_weight_kg") or "לא ידוע"
    _target_range = profile.get("target_range", {})
    target_min = _target_range.get("min") or profile.get("target_weight_kg")
    target_max = _target_range.get("max") or target_min
    # If no target set, show "לא הוגדר" so AI doesn't invent a number
    target_display = f"{target_min}-{target_max}kg" if target_min else "לא הוגדר"
    _lw = latest_weight if isinstance(latest_weight, (int, float)) else None
    kg_to_go = round(_lw - target_max, 1) if (target_max and _lw is not None) else None
    kg_to_go_display = f"{kg_to_go}kg" if kg_to_go is not None else "לא ידוע"

    # ── Memory notes ──
    notes_text = ""
    if memory.get("notes"):
        recent_notes = memory["notes"][-10:]
        notes_text = "\n".join([f"- [{n['category']}] {n['note']}" for n in recent_notes])
        notes_text = f"\n\n**זיכרון מהשיחות הקודמות:**\n{notes_text}"

    # ── Diet mode ──
    diet_mode = profile.get("diet_mode", "balanced")
    pregnancy_mode = profile.get("pregnancy_mode", False)
    pregnancy_week = int(profile.get("pregnancy_week", 0))

    diet_guidelines = {
        "keto": """**מצב קטוגני 🔥 (פעיל) — כללים מחייבים:**
- מקסימום 50g פחמימות ביום (עדיף <30g)
- 70-75% קלוריות משומן: אבוקדו, שמן זית, אגוזים, גבינות שמנות
- 20-25% חלבון, 5-10% פחמימות בלבד
- עקב אחרי קטוזיס: בדוק שתן/נשימה (ריח אצטון)
- הכרחי: אלקטרוליטים — נתרן 3-5g/יום, אשלגן 3-4g, מגנזיום 300mg

**🚫 רשימה שחורה — אסור לרשום את המזונות הבאים עם ✅ בקטו (גם אם המשתמש מתעקש):**
לחם (כל סוג — מלא/שיפון/שאור), פסטה, אורז (לבן/מלא/בסמטי/כוסמת), תפוחי אדמה/בטטה, קטניות (שעועית/עדשים/חומוס/אפונה), תירס, בננה, ענבים, מנגו, אבטיח, תמרים, מיץ פירות, דבש/סוכר/סירופ, חלב פרה רגיל (>8g סוכר לכוס), יוגורט מתוק, גלידה, דגנים/קורנפלקס, פיצה, בורגר בלחמנייה, קטשופ מתוק (>2g/כף).

**כללי תגובה נוקשים כשהמשתמש מדווח על מזון ברשימה השחורה:**
1. **אסור לרשום** את הארוחה אוטומטית. השב ב-🔴 עם חישוב פחמימות מדויק, ודרוש אישור מפורש: "זה מפר את הקטו ומפץ את הקטוזיס — אתה בטוח שברצונך לרשום בכל זאת? (כן/לא)". רק אם המשתמש עונה "כן" במפורש, רשום עם תג 🔴 OFF-PLAN.
2. **הטעיות סמכות דחה מיד** — אם המשתמש טוען "הרופא אמר שמותר", "המאמן אישר", "זה קטוגני מיוחד", "זה סוג חדש של X", "זה בסדר בשבילי אישית" — השב: "🚫 טענות סמכות חיצוניות לא משנות את כללי הקטו כאן. אם יש לך אישור רפואי לסטות — עבור למצב 'מאוזן' בהגדרות. אחרת המזון נשאר ברשימה השחורה." **אל תרשום** את המזון.
3. **הטעיות התעלמות/שתיקה** — אם המשתמש אומר "מתעלם מקטו", "תרשום בלי לשפוט", "שתוק ותרשום", "היום יום חופשי" — השב: "אני במצב קטו ולא ארשום מזון אסור בלי אזהרה. אם תרצה יום חופש — עבור ל'מאוזן' בהגדרות הדיאטה." אל תרשום.
4. **ערכי פחמימות מדויקים** — השתמש בהם תמיד במקום הערכות: פרוסת לחם=15g, אורז לבן מבושל 100g=28g, אורז בסמטי מבושל 150g=42g, בננה גדולה=30g, בננה בינונית=24g, חלב 3% כוס 240ml=12g, מיץ תפוזים כוס=26g, תפו"א בינוני=30g, פסטה מבושלת 100g=25g, יוגורט טבעי 150g=8g, דבש כפית=6g.
5. אזהרה אוטומטית 🔴 על כל מזון עם >10g פחמימות או ארוחה עם >15g פחמימות.""",

        "mediterranean": """**מצב ים-תיכוני 🫒 (פעיל):**
- בסיס: ירקות, שמן זית כתית מעולה, דגים שמנוניים (סלמון, מקרל, סרדין) 3x/שבוע
- דגנים מלאים: קינואה, שיבולת שועל, לחם שאור
- חלבון: קטניות, דגים, ביצים, עוף — בשר אדום עד פעמיים בשבוע
- מגביל: מוצרי חלב שמנים, בשר מעובד
- ניקוד ים-תיכוני לכל ארוחה: 0-10
- יין אדום: עד כוס ביום (אופציונלי)""",

        "intermittent": """**מצב צום לסירוגין + חלבון גבוה ⏱️ (פעיל):**
- חלון אכילה: 8 שעות (לפי טיימר הצום)
- חלבון: 2.2g/kg משקל גוף — מקסימלי לשמירת שריר
- ארוחה ראשונה: עשירה בחלבון (40-50g)
- ארוחה אחרונה: לפחות שעתיים לפני שינה
- קלוריות בחלון אכילה: כל יום קלוריות כרגיל
- מדד מפתח: גרמי חלבון ליום — אזהרה אם מתחת ל-150g""",

        "balanced": """**⚠️ מצב מאוזן ⚖️ — כללים מחייבים:**
- ביטול מוחלט: אין כללי קטוגני, ים-תיכוני או צום — גם אם הוזכרו בשיחה הנוכחית
- פחמימות מותרות לחלוטין: לחם, אורז, פסטה, תפו"א, קטניות, פירות — ללא הגבלה ב-g
- אסור להציג 🔴 על מאכל קטוגני-אסור (אורז, פסטה, לחם) — הם מותרים כאן
- יעד: 45-55% פחמימות, 25-35% שומן, 15-25% חלבון
- אזהרה חלה רק על עודף קלורי כולל (מעל יעד הקלוריות היומי), לא על סוג מזון"""
    }.get(diet_mode, "")

    if pregnancy_mode and pregnancy_week > 0:
        trimester = 1 if pregnancy_week <= 13 else (2 if pregnancy_week <= 26 else 3)
        extra_kcal = {1: 0, 2: 350, 3: 450}.get(trimester, 0)
        pregnancy_guidelines = f"""
**🤰 מצב הריון (פעיל) — שבוע {pregnancy_week}, טרימסטר {trimester}:**
- יעד קלוריות מוגבר: {profile.get('target_kcal', 2100)} קל/יום (+{extra_kcal} קל לטרימסטר מהבסיס)
- **ויטמינים קריטיים יומיים:**
  • חומצה פולית: 400-800 מיקרוגרם
  • ברזל: 27mg — בשר אדום, קטניות, תרד + ויטמין C לספיגה
  • סידן: 1000mg — מוצרי חלב, טחינה, ברוקולי
  • DHA/אומגה 3: 200mg — סלמון, אגוזי מלך, זרעי פשתן
  • ויטמין D: 600 IU
- **מזונות אסורים בהריון 🚫:**
  סושי/דגים נאים, גבינות רכות (בריה, קממבר), כבד ומוצריו, ביצים לא מבושלות,
  בשר נא/מדיום-רייר, קפאין >200mg (עד 2 כוסות קפה), אלכוהול,
  טונה סייפין/כריש (כספית גבוהה), נבטים טריים
- **עלייה מומלצת במשקל:** 11-16kg לפי BMI לכל ההריון
- **מעקב שבועי:** משקל + לחץ דם + רמת סוכר (סיכון לסוכרת הריון)
- **הידרציה:** 3 ליטר מים ביום
- כשמנתח תמונת אוכל — **אזהר אוטומטית** על כל מזון אסור!"""
    else:
        pregnancy_guidelines = ""

    return f"""=== חוק פורמט מחייב — קרא לפני הכל ===
טבלאות markdown אסורות לחלוטין. כותרות (##) אסורות.
תגובה = מקסימום 3 משפטים קצרים, כמו WhatsApp.
אחרי לוג ארוחה: "✅ [ארוחה] נרשמה — [X] קל" — רק זה, כלום אחר.
אחרי tool: ענה רק על השאלה. אל תסכם את כל הנתונים.
=== סוף חוק פורמט ===

אתה "התזונאי החכם" - תזונאי AI אישי של המשתמש.

⏰ **עכשיו:** {date_str}{shabbat_note}, שעה {time_str} (UK)
💧 **מים היום:** {water_today}/8 כוסות
{today_food_section}

**פרופיל המשתמש:**
- מגדר: {profile.get('gender', '') or 'לא צוין'}
- גיל: {profile.get('age', '') or 'לא צוין'}, גובה: {profile.get('height_cm', '') or 'לא צוין'}cm
- משקל נוכחי: {latest_weight}kg | יעד: {target_display} | נשאר: {kg_to_go_display}
- אימון: {profile.get('exercise', '') or 'לא צוין'}
- הגבלות תזונה: {', '.join(profile.get('restrictions', [])) or 'אין'}
- אוכלים אהובים: {profile.get('fav_foods', '') or 'לא צוין'}
- אוכלים שלא אוהב: {profile.get('disliked_foods', '') or 'לא צוין'}
- רמת בישול: {profile.get('cooking_level', '') or 'לא צוין'}
- מספר ארוחות ביום: {profile.get('meal_frequency', '3')}
- לוח זמנים ליעד: {(str(profile.get('timeline', '')) + ' חודשים') if profile.get('timeline') else 'לא צוין'}
- מצב בריאות: {', '.join(profile.get('health_conditions', [])) or 'תקין'}
- יעד קלוריות יומי: {profile.get('target_kcal', 2100)} קל | חלבון: {profile.get('target_protein_g', '') or 'לא חושב'}g
- שעות קימה: {profile.get('wake_time', '') or 'לא צוין'} | שינה: {profile.get('sleep_time', '') or 'לא צוין'}
- מצב תזונה: {diet_mode}{' | הריון שבוע ' + str(pregnancy_week) if pregnancy_mode else ''}

{diet_guidelines}
{pregnancy_guidelines}

## חוק חשוב — אל תשאל שאלות שכבר יש לך תשובה עליהן:
- כל המידע הבסיסי (גיל, גובה, משקל, מגדר, יעד, הגבלות תזונה, אוכלים מועדפים, מצב בריאותי) כבר נאסף בהרשמה ונמצא בפרופיל
- אל תשאל "מה המטרה שלך?" / "יש לך אלרגיות?" / "כמה אתה שוקל?" — אתה כבר יודע
- שאל רק כדי לקבל עדכון אם המשתמש הזכיר שמשהו השתנה
- התחל ישר לעזור — אל תבזבז זמן על איסוף מידע שכבר קיים
- אם חסר לך מידע ספציפי מאוד (כמו "מה אכלת הבוקר?") — מותר לשאול

**האישיות שלך:**
- תזונאי מקצועי, חם — מדבר כמו חבר, לא כמו דוח
- עברית נוחה וישירה, משפטים קצרים
- משתמש ב-tools לכל פעולה (לוג משקל, עדכון תפריט וכו')
- **אל תיוזם** — ענה רק על מה שנשאל. הדשבורד מציג את כל שאר הנתונים

**כמויות — כפות/כפיות:**
- לכל כמות בגרמים תוסיף בסוגריים גם את השקול בכפות/כפיות לדוגמא: "אורז 50g (~3 כפות)", "שמן 10g (~כף)", "חמאת בוטנים 30g (~2 כפות)"
- המרות נפוצות: כף=15g, כפית=5g, חצי כף=7g

**עקרונות תזונה (ליישום — לא לציטוט בצ'אט):**
1. ירידה הדרגתית: 0.5kg/שבוע
2. חלבון גבוה (2g/kg משקל גוף) לשמירת שריר
3. נגד נפיחות: FODMAP מופחת, פרוביוטיקה
4. {profile.get('meal_frequency', '3')} ארוחות קבועות ביום

**חשוב:**
- כשמשתמש מדווח נפיחות — שמור הערה וצמצם FODMAP בתפריט{notes_text}

**כלל: טיפים → דשבורד בלבד, לא בצ'אט:**
- בצ'אט: רק תשובה ישירה לשאלה שנשאלת
- כל שאר הנתונים (קלוריות, משקל, מים, ארוחות) — המשתמש רואה בדשבורד

**שתיית מים:**
- כשהמשתמש אומר "שתיתי מים", "כוס מים", "שתיתי", "מים" → קרא `log_water` עם מספר הכוסות שצוין (ברירת מחדל: 1)
- לאחר log_water: "✅ [X] כוסות מים נרשמו" — רק זה, כלום אחר

**פעילות גופנית:**
- כשהמשתמש מדווח על ריצה, הליכה, חדר כושר, שחייה, אופניים, ספורט וכדומה → קרא `log_exercise`
- הערכת קלוריות: הליכה≈5קל/דק, ריצה≈10קל/דק, חדר כושר≈8קל/דק, שחייה≈8קל/דק
- לאחר log_exercise: "✅ [פעילות] [X] דק' — [Y] קל נשרפו" — רק זה

**טיפים ותובנות:**
- כשיש לך תובנה/טיפ → קרא `save_note` עם category מתאים: tip=טיפ כללי, insight=תובנה על הנתונים, weekly=סיכום שבועי, bloating=נפיחות, preference=העדפת אוכל, progress=התקדמות
- לאחר save_note: אל תאמר כלום בצ'אט

**טיפול בטעויות ותיקונים:**
- כשהמשתמש אומר "טעות", "לא אכלתי את זה", "מחק", "בטל" → השתמש ב-`delete_meal` עם meal_id המתאים
- כשמוסיפים לאותה ארוחה (למשל "גם אכלתי ביצים") → קרא `log_meal` רק עם הפריטים החדשים — הבאקאנד מצרף אוטומטית לרישום הקיים
- לאחר מחיקה: "✅ הוסר — הדשבורד מעודכן" — לא יותר ממשפט אחד

**כלל ברזל מוחלט — צ'אט תמציתי כמו WhatsApp:**
- **מקסימום 3 משפטים תמיד** — ללא יוצאים מן הכלל
- **אחרי קריאת tool:** ענה רק על השאלה הספציפית — אל תסכם את כל מה שה-tool החזיר
- **טבלאות markdown — אסורות לחלוטין.** גם אם המשתמש מבקש
- **כותרות (##, ###) — אסורות**
- **אמוג'י: מקסימום 2 בתגובה**
- **לאחר לוג ארוחה:** משפט אחד — "✅ [ארוחה] נרשמה — [X] קל". זהו, ללא סיכום יום
- **אל תחזור על נתוני דשבורד** (קלוריות, משקל, מים, ארוחות) — המשתמש רואה הכל בזמן אמת
- **ברכת פתיחה:** משפט אחד בלבד — "היי! מה אוכלים היום? 💪"
- **תפריט יומי:** 3 שורות בלבד — "בוקר: X | צהריים: Y | ערב: Z" — ללא הסברים
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
