# 🥗 NutriAI Telegram Bot — מדריך הגדרה

> בוט שיווק אוטומטי לערוץ Telegram בעברית, מבוסס `python-telegram-bot` v20+

---

## תוכן עניינים

1. [יצירת בוט ב-BotFather](#1-יצירת-בוט-ב-botfather)
2. [יצירת ערוץ והוספת הבוט כאדמין](#2-יצירת-ערוץ-והוספת-הבוט-כאדמין)
3. [הגדרת משתני סביבה](#3-הגדרת-משתני-סביבה)
4. [הרצה מקומית](#4-הרצה-מקומית)
5. [פריסה ל-Render (חינם)](#5-פריסה-ל-render-חינם)
6. [פקודות אדמין](#6-פקודות-אדמין)
7. [מבנה הפרויקט](#7-מבנה-הפרויקט)

---

## 1. יצירת בוט ב-BotFather

1. פתחו Telegram וחפשו את **@BotFather**
2. שלחו את הפקודה: `/newbot`
3. BotFather ישאל אתכם לשם הבוט — הזינו שם תצוגה, לדוגמה:
   ```
   NutriAI Marketing Bot
   ```
4. לאחר מכן הוא ישאל לשם משתמש (username) — חייב להסתיים ב-`bot`:
   ```
   NutriAIMarketingBot
   ```
5. BotFather יחזיר לכם **טוקן API** שנראה כך:
   ```
   123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
   ```
   **שמרו את הטוקן הזה בסוד — אל תעלו אותו ל-GitHub!**

6. (אופציונלי) הגדרו תיאור לבוט:
   ```
   /setdescription
   ```
   והזינו:
   ```
   בוט תזונה אוטומטי של NutriAI 🥗
   ```

---

## 2. יצירת ערוץ והוספת הבוט כאדמין

### יצירת הערוץ

1. בטלגרם לחצו על **עיפרון / New Channel**
2. בחרו שם לערוץ, לדוגמה: `NutriAI — טיפים תזונתיים יומיים`
3. בחרו **Public Channel** והגדירו שם משתמש, לדוגמה: `@NutriAITips`
4. לחצו **Create**

### הוספת הבוט כאדמין

1. היכנסו לערוץ שיצרתם
2. לחצו על שם הערוץ בראש המסך → **Administrators**
3. לחצו **Add Administrator**
4. חפשו את שם המשתמש של הבוט שיצרתם (לדוגמה `@NutriAIMarketingBot`)
5. הפעילו את ההרשאות הבאות:
   - ✅ **Post Messages**
   - ✅ **Edit Messages**
   - ✅ **Delete Messages**
   - ✅ **Add Members** (לקבלת אירועי הצטרפות)
6. לחצו **Save**

### קבלת מזהה הערוץ (Channel ID)

**אפשרות א׳ — שם משתמש ציבורי:**
אם הערוץ שלכם ציבורי ויש לו `@username`, פשוט השתמשו בו:
```
@NutriAITips
```

**אפשרות ב׳ — מזהה מספרי (לערוץ פרטי):**
1. הוסיפו את הבוט `@userinfobot` לערוץ
2. שלחו הודעה כלשהי בערוץ
3. `@userinfobot` יחזיר את ה-ID המספרי שמתחיל ב-`-100`, לדוגמה:
   ```
   -1001234567890
   ```

---

## 3. הגדרת משתני סביבה

### שיטה א׳ — קובץ `.env` (לפיתוח מקומי)

צרו קובץ בשם `.env` בתיקיית `telegram_bot/`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHANNEL_ID=@NutriAITips
```

**חשוב:** הוסיפו את `.env` לקובץ `.gitignore` שלכם!

```bash
echo ".env" >> .gitignore
```

### שיטה ב׳ — משתני סביבה ישירים (לשרת / Render)

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ"
export TELEGRAM_CHANNEL_ID="@NutriAITips"
```

---

## 4. הרצה מקומית

### דרישות מוקדמות

- Python 3.10 ומעלה
- pip

### התקנת תלויות

```bash
cd telegram_bot
pip install -r requirements.txt
```

### הרצת הבוט

```bash
python bot.py
```

הבוט יתחיל לרוץ וייכנס ל-polling mode. תראו לוג כזה:

```
2026-04-08 07:00:00 | INFO | nutriai_bot | Starting NutriAI Telegram Bot...
2026-04-08 07:00:00 | INFO | nutriai_bot | Channel: @NutriAITips
2026-04-08 07:00:00 | INFO | nutriai_bot | Bot is running. Scheduled posts at 07:00, 13:00, 20:00 (IL time)
```

לעצירת הבוט: **Ctrl+C**

---

## 5. פריסה ל-Render (חינם)

### שלב א׳ — הכנת הקוד ל-Render

ודאו שהקבצים הבאים קיימים בתיקיית הפרויקט:

```
telegram_bot/
├── bot.py
├── content.py
├── requirements.txt
└── render.yaml        ← צרו אותו (ראו למטה)
```

צרו קובץ `render.yaml` בתיקיית `telegram_bot/`:

```yaml
services:
  - type: worker
    name: nutriai-telegram-bot
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: python bot.py
    envVars:
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHANNEL_ID
        sync: false
```

### שלב ב׳ — יצירת חשבון Render

1. גשו ל-[render.com](https://render.com) וצרו חשבון חינמי
2. חברו את חשבון GitHub שלכם

### שלב ג׳ — העלאת הקוד ל-GitHub

```bash
git add telegram_bot/
git commit -m "Add NutriAI Telegram bot"
git push origin main
```

### שלב ד׳ — יצירת שירות ב-Render

1. ב-Render dashboard לחצו **New +** → **Worker**
2. בחרו את ה-repository שלכם
3. הגדרות:
   - **Name:** `nutriai-telegram-bot`
   - **Region:** Frankfurt (EU) — הכי קרוב לישראל
   - **Branch:** `main`
   - **Build Command:** `pip install -r telegram_bot/requirements.txt`
   - **Start Command:** `python telegram_bot/bot.py`
   - **Plan:** Free

### שלב ה׳ — הוספת משתני סביבה ב-Render

1. בדף השירות לחצו על **Environment**
2. הוסיפו:
   - `TELEGRAM_BOT_TOKEN` = הטוקן שלכם
   - `TELEGRAM_CHANNEL_ID` = מזהה הערוץ שלכם
3. לחצו **Save Changes**

### שלב ו׳ — Deploy

לחצו **Deploy Latest Commit** — הבוט יעלה ויתחיל לעבוד!

> **שימו לב:** ב-Render Free Tier, Worker dyno לא נכבה אוטומטית (בניגוד ל-Web Service).
> הבוט ירוץ ברצף ללא הפרעה.

---

## 6. פקודות אדמין

שלחו את הפקודות האלה ישירות לבוט בצ'אט פרטי:

| פקודה | תיאור |
|-------|--------|
| `/post` | שליחת פוסט מיידי לערוץ (ללא המתנה לשעה המתוכננת) |
| `/stats` | הצגת סטטיסטיקות — מנויים, פוסטים שנשלחו |
| `/schedule` | הצגת לוח הפוסטים להיום |

---

## 7. מבנה הפרויקט

```
telegram_bot/
├── bot.py            # קוד הבוט הראשי
├── content.py        # ספריית תוכן עברית (30 טיפים, 7 אתגרים, מתכונים...)
├── requirements.txt  # תלויות Python
├── .env              # משתני סביבה (לא מועלה ל-Git!)
└── README.md         # מדריך זה
```

### לוח שידורים אוטומטי

| שעה (IL) | ימים | תוכן |
|----------|------|-------|
| 07:00 | כל יום | טיפ תזונתי בוקר |
| 13:00 | כל יום | עובדה / מתכון / ציטוט מוטיבציוני (מסתובב) |
| 20:00 | כל יום | טיפ תזונתי ערב |
| 09:00 | ראשון בלבד | אתגר שבועי |

---

## שאלות נפוצות

**ש: הבוט לא שולח לערוץ — מה קורה?**
ב: ודאו שהבוט הוגדר כ-Administrator בערוץ עם הרשאת Post Messages.

**ש: אני מקבל שגיאה `TELEGRAM_BOT_TOKEN not set`**
ב: ודאו שהקובץ `.env` קיים בתיקיית הרצת הסקריפט, או שמשתני הסביבה מוגדרים ישירות.

**ש: איך אני מוסיף תוכן חדש?**
ב: ערכו את `content.py` — הוסיפו פריטים לרשימות `DAILY_TIPS`, `WEEKLY_CHALLENGES` וכו'.

**ש: האם הבוט תואם ל-Render Free Tier?**
ב: כן! Worker dyno ב-Render רץ ברצף ללא כיבוי אוטומטי, מתאים לבוט שמשתמש ב-polling.

---

*NutriAI — המאמן התזונתי שלך 🥗 | [nutri-ai.app](https://nutri-ai.app)*
