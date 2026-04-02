"""
Windows notification system for the nutritionist agent.
Uses PowerShell to send Windows 11 toast notifications.
"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DATA_DIR = Path(__file__).parent / "data"


def send_windows_toast(title: str, message: str, duration: int = 10):
    """Send a Windows 11 toast notification via PowerShell."""
    # Escape quotes for PowerShell
    title = title.replace('"', '`"').replace("'", "`'")
    message = message.replace('"', '`"').replace("'", "`'")

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$APP_ID = "NutritionistAgent"

$template = @"
<toast duration="long">
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{message}</text>
    </binding>
  </visual>
  <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($APP_ID).Show($toast)
"""
    try:
        result = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            # Fallback: use msg box
            _fallback_notification(title, message)
    except Exception as e:
        _fallback_notification(title, message)


def _fallback_notification(title: str, message: str):
    """Fallback balloon tip notification."""
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$global:balloon = New-Object System.Windows.Forms.NotifyIcon
$path = (Get-Process -id $pid).Path
$balloon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($path)
$balloon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$balloon.BalloonTipText = '{message}'
$balloon.BalloonTipTitle = '{title}'
$balloon.Visible = $true
$balloon.ShowBalloonTip(10000)
Start-Sleep -Seconds 3
$balloon.Dispose()
"""
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, timeout=15
        )
    except Exception:
        # Last resort: print to console
        print(f"\n{'='*50}")
        print(f"  {title}")
        print(f"  {message}")
        print(f"{'='*50}\n")


def notify_meal_reminder(meal_id: str):
    """Send a meal reminder notification."""
    try:
        with open(DATA_DIR / "meal_plan.json", encoding="utf-8") as f:
            plan = json.load(f)

        meal = next((m for m in plan["meal_schedule"] if m["id"] == meal_id), None)
        if not meal:
            return

        # Get today's day
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        today = days[datetime.now().weekday()]

        weekly = plan.get("weekly_plan", {}).get(today, {})
        meal_today = weekly.get(meal_id, {})
        items = meal_today.get("items", [])
        note = meal_today.get("notes", "")

        title = f"{meal['emoji']} {meal['name']} בעוד 5 דקות!"

        if items:
            # Show first 2 items
            items_preview = " | ".join(items[:2])
            if len(items) > 2:
                items_preview += f" + {len(items)-2} עוד"
            body = f"{items_preview}"
            if note:
                body += f"\n💡 {note}"
        else:
            body = f"זמן ל{meal['name']}! {meal['target_kcal']} קלוריות"

        send_windows_toast(title, body)
        print(f"[{datetime.now().strftime('%H:%M')}] התראה נשלחה: {title}")

        # Log the notification
        _log_notification(meal_id, meal['name'])

    except Exception as e:
        print(f"שגיאה בשליחת התראה: {e}")


def notify_custom(title: str, message: str):
    """Send a custom notification."""
    send_windows_toast(title, message)


def _log_notification(meal_id: str, meal_name: str):
    """Log that a notification was sent."""
    try:
        progress_file = DATA_DIR / "progress.json"
        with open(progress_file, encoding="utf-8") as f:
            progress = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")
        entry = {
            "date": today,
            "time": datetime.now().strftime("%H:%M"),
            "meal_id": meal_id,
            "meal_name": meal_name,
            "notified": True
        }
        progress["meal_log"].append(entry)

        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


if __name__ == "__main__":
    # Called from command line: python notifier.py <meal_id>
    # Or: python notifier.py test
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "test":
            send_windows_toast(
                "🥗 בדיקת מערכת - התזונאי החכם",
                "ההתראות עובדות! אני כאן ללוות אותך לאורך כל היום 💪"
            )
            print("התראת בדיקה נשלחה!")
        else:
            notify_meal_reminder(arg)
