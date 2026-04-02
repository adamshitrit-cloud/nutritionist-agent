"""
Meal reminder scheduler - runs in the background and sends
Windows notifications 5 minutes before each scheduled meal.
"""
import schedule
import time
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"


def load_meal_plan() -> dict:
    plan_file = DATA_DIR / "meal_plan.json"
    if plan_file.exists():
        with open(plan_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def send_reminder(meal_id: str):
    """Trigger the notifier for a given meal."""
    notifier = BASE_DIR / "notifier.py"
    python = sys.executable
    try:
        subprocess.Popen(
            [python, str(notifier), meal_id],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
    except Exception as e:
        print(f"[scheduler] שגיאה בשליחת התראה ל-{meal_id}: {e}")


def send_morning_motivation():
    """Send a morning motivational message."""
    notifier = BASE_DIR / "notifier.py"
    python = sys.executable
    from notifier import send_windows_toast
    try:
        send_windows_toast(
            "☀️ בוקר טוב! יום חדש, הזדמנות חדשה",
            "זכור: ארוחת בוקר ב-7:30 • אתה בדרך ל-85kg 💪"
        )
    except Exception:
        pass


def send_hydration_reminder():
    """Remind to drink water."""
    try:
        from notifier import send_windows_toast
        hour = datetime.now().hour
        if 8 <= hour <= 21:
            send_windows_toast(
                "💧 תזכורת שתייה",
                "שתית מספיק מים היום? שאף ל-8-10 כוסות ביום"
            )
    except Exception:
        pass


def setup_schedule():
    """Set up all meal reminders based on meal_plan.json."""
    plan = load_meal_plan()
    meal_schedule = plan.get("meal_schedule", [])

    print(f"[{datetime.now().strftime('%H:%M')}] מגדיר תזכורות ארוחות...")

    for meal in meal_schedule:
        reminder_time = meal.get("reminder_time")
        meal_id = meal["id"]
        meal_name = meal["name"]

        if reminder_time:
            schedule.every().day.at(reminder_time).do(send_reminder, meal_id=meal_id)
            print(f"  ✓ {meal_name} - תזכורת ב-{reminder_time}")

    # Morning motivation at 7:05
    schedule.every().day.at("07:05").do(send_morning_motivation)
    print("  ✓ מוטיבציה בוקר - 07:05")

    # Hydration reminders
    for water_time in ["09:00", "11:00", "15:00", "17:00"]:
        schedule.every().day.at(water_time).do(send_hydration_reminder)

    print(f"\n✅ {len(meal_schedule)} תזכורות ארוחות פעילות")
    print("💧 4 תזכורות שתייה פעילות")
    print("\nהמתנה לתזכורות הבאות...\n")


def run_scheduler():
    """Main scheduler loop."""
    print("="*50)
    print("  🗓️ תזמון ארוחות - התזונאי החכם")
    print("="*50)

    setup_schedule()

    # Show next scheduled jobs
    print("לחץ Ctrl+C לעצירה\n")

    while True:
        schedule.run_pending()

        # Check every 30 seconds
        now = datetime.now()

        # Show heartbeat every 5 minutes
        if now.second < 30 and now.minute % 5 == 0:
            next_job = schedule.next_run()
            if next_job:
                diff = next_job - now
                minutes = int(diff.total_seconds() / 60)
                if minutes > 0:
                    print(f"[{now.strftime('%H:%M')}] תזכורת הבאה בעוד {minutes} דקות")

        time.sleep(30)


if __name__ == "__main__":
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("\n\nהמתזמן הופסק. להתראות!")
