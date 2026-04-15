# -*- coding: utf-8 -*-
"""
UI translations for chat.html. Single source of truth for all 4 supported languages.

Structure:
  UI_STRINGS[key] = {"he": ..., "en": ..., "ar": ..., "ru": ...}

Helpers:
  get_ui_strings(lang) -> flat dict {key: value} for the target language
                          (falls back to English if a key is missing in that lang)

Keys are english-based snake_case so the code is self-documenting.
"""

UI_STRINGS = {
    # ── Sidebar: biomarkers ──
    "biomarkers":            {"he": "נתוני בריאות",     "en": "BIOMARKERS",       "ar": "مؤشرات صحية",         "ru": "БИОМАРКЕРЫ"},
    "body_mass":             {"he": "משקל גוף",         "en": "BODY MASS",        "ar": "كتلة الجسم",          "ru": "МАССА ТЕЛА"},
    "target":                {"he": "יעד",              "en": "TARGET",           "ar": "الهدف",                "ru": "ЦЕЛЬ"},
    "delta_weight":          {"he": "שינוי משקל",       "en": "ΔWEIGHT",          "ar": "تغير الوزن",          "ru": "ΔВЕС"},
    "progress_to_goal":      {"he": "התקדמות לקראת היעד","en": "Progress to goal","ar": "التقدم نحو الهدف",    "ru": "Прогресс к цели"},
    "weight_trajectory":     {"he": "מסלול משקל",       "en": "WEIGHT TRAJECTORY","ar": "مسار الوزن",          "ru": "ТРАЕКТОРИЯ ВЕСА"},
    "weight_log":            {"he": "יומן משקל",        "en": "WEIGHT LOG",       "ar": "سجل الوزن",           "ru": "ЖУРНАЛ ВЕСА"},
    "calories":              {"he": "קלוריות",          "en": "Calories",         "ar": "سعرات",               "ru": "Калории"},
    "caloric_load":          {"he": "עומס קלורי",       "en": "CALORIC LOAD",     "ar": "الحمل الحراري",       "ru": "КАЛОРИЙНАЯ НАГРУЗКА"},
    "of_target":             {"he": "מתוך",             "en": "of",               "ar": "من",                   "ru": "из"},
    "streak_days":           {"he": "רצף ימים",         "en": "Streak",           "ar": "سلسلة أيام",          "ru": "Серия"},
    "streak_caps":           {"he": "רצף ימים",         "en": "STREAK",           "ar": "سلسلة الأيام",        "ru": "СЕРИЯ"},
    "log_meal_to_start":     {"he": "רשום ארוחה כדי להתחיל!", "en": "Log a meal to start!", "ar": "سجّل وجبة لتبدأ!", "ru": "Запишите блюдо, чтобы начать!"},
    "water":                 {"he": "מים",              "en": "Water",            "ar": "ماء",                 "ru": "Вода"},
    "hydration":             {"he": "הידרציה",          "en": "HYDRATION",        "ar": "الترطيب",              "ru": "ГИДРАТАЦИЯ"},
    "glasses":               {"he": "כוסות",            "en": "glasses",          "ar": "أكواب",               "ru": "стаканов"},
    "water_drop_tooltip":    {"he": "לחץ להוסיף, לחיצה כפולה לאיפוס", "en": "Click to add, double-click to reset", "ar": "انقر للإضافة، نقر مزدوج للتصفير", "ru": "Нажмите чтобы добавить, двойной клик — сброс"},
    "body_measurements":     {"he": "מדידות גוף",       "en": "Body Measurements","ar": "قياسات الجسم",        "ru": "Замеры тела"},
    "latest_measurement":    {"he": "מדידה אחרונה",     "en": "Latest Measurement","ar": "آخر قياس",            "ru": "Последний замер"},
    "not_yet_measured":      {"he": "טרם נמדד",         "en": "Not yet measured", "ar": "لم يُقاس بعد",        "ru": "Еще не измерено"},
    "pregnancy":             {"he": "מעקב הריון",       "en": "Pregnancy",        "ar": "متابعة الحمل",        "ru": "Беременность"},
    "pregnancy_week":        {"he": "שבוע (1-42)",      "en": "Week (1-42)",      "ar": "أسبوع (1-42)",        "ru": "Неделя (1-42)"},
    "save":                  {"he": "שמור",             "en": "Save",             "ar": "حفظ",                 "ru": "Сохранить"},
    "daily_vitamins":        {"he": "ויטמינים יומיים",  "en": "Daily Vitamins",   "ar": "فيتامينات يومية",     "ru": "Ежедневные витамины"},
    "folic_acid":            {"he": "חומצה פולית",      "en": "Folic Acid",       "ar": "حمض الفوليك",         "ru": "Фолиевая кислота"},
    "iron":                  {"he": "ברזל",             "en": "Iron",             "ar": "حديد",                "ru": "Железо"},
    "calcium":               {"he": "סידן",             "en": "Calcium",          "ar": "كالسيوم",             "ru": "Кальций"},
    "omega_3":               {"he": "אומגה 3",          "en": "Omega-3",          "ar": "أوميغا 3",            "ru": "Омега-3"},
    "vitamin_d":             {"he": "ויטמין D",         "en": "Vitamin D",        "ar": "فيتامين D",           "ru": "Витамин D"},
    "blood_tests":           {"he": "בדיקות דם",        "en": "Blood Tests",      "ar": "فحوصات الدم",         "ru": "Анализы крови"},
    "what_food_to_check":    {"he": "מה המזון לבדיקה?", "en": "What food to check?", "ar": "ما الطعام للفحص؟", "ru": "Какой продукт проверить?"},
    "check_is_safe":         {"he": "בדוק: האם מותר לאכול?", "en": "Check: Is this food safe?", "ar": "افحص: هل الطعام آمن؟", "ru": "Проверить: безопасно ли?"},
    "diet_mode":             {"he": "מצב תזונה",        "en": "Diet Mode",        "ar": "نمط التغذية",         "ru": "Режим питания"},
    "diet_balanced":         {"he": "מאוזן",            "en": "Balanced",         "ar": "متوازن",              "ru": "Сбалансированная"},
    "diet_keto":             {"he": "קטוגני",           "en": "Keto",             "ar": "كيتو",                "ru": "Кето"},
    "diet_mediterranean":    {"he": "ים-תיכוני",        "en": "Mediterranean",    "ar": "متوسطي",              "ru": "Средиземноморская"},
    "diet_if_protein":       {"he": "צום+חלבון",        "en": "IF+Protein",       "ar": "صيام+بروتين",         "ru": "ИГ+Белок"},
    "calorie_burn":          {"he": "שריפת קלוריות",    "en": "Calorie Burn",     "ar": "حرق السعرات",         "ru": "Сжигание калорий"},
    "today":                 {"he": "היום",             "en": "Today",            "ar": "اليوم",               "ru": "Сегодня"},
    "week":                  {"he": "שבוע",             "en": "Week",             "ar": "أسبوع",               "ru": "Неделя"},
    "month":                 {"he": "חודש",             "en": "Month",            "ar": "شهر",                 "ru": "Месяц"},
    "net_calories_today":    {"he": "קלוריות נטו היום", "en": "Net calories today","ar": "صافي السعرات اليوم","ru": "Чистые калории сегодня"},
    "fasting_timer":         {"he": "טיימר צום",        "en": "Fasting Timer",    "ar": "مؤقت الصيام",         "ru": "Таймер поста"},
    "actions":               {"he": "פעולות מהירות",    "en": "ACTIONS",          "ar": "إجراءات سريعة",       "ru": "ДЕЙСТВИЯ"},
    "weekly_plan":           {"he": "תפריט שבועי",      "en": "Weekly Plan",      "ar": "خطة أسبوعية",         "ru": "План недели"},
    "progress":              {"he": "התקדמות",          "en": "Progress",         "ar": "التقدم",              "ru": "Прогресс"},
    "log_weight":            {"he": "עדכן משקל",        "en": "Log Weight",       "ar": "تسجيل الوزن",         "ru": "Записать вес"},
    "send_food_photo":       {"he": "שלח תמונת אוכל",   "en": "Send Food Photo",  "ar": "أرسل صورة طعام",      "ru": "Отправить фото еды"},
    "shopping_list":         {"he": "רשימת קניות",      "en": "Shopping List",    "ar": "قائمة تسوق",          "ru": "Список покупок"},
    "weekly_report":         {"he": "דוח שבועי",        "en": "Weekly Report",    "ar": "تقرير أسبوعي",        "ru": "Недельный отчёт"},
    "notifications":         {"he": "התראות",           "en": "Notifications",    "ar": "إشعارات",             "ru": "Уведомления"},
    "share_progress":        {"he": "שתף התקדמות",      "en": "Share Progress",   "ar": "مشاركة التقدم",       "ru": "Поделиться прогрессом"},
    "barcode_scan":          {"he": "סריקת ברקוד",      "en": "Barcode Scan",     "ar": "مسح الباركود",        "ru": "Скан штрихкода"},
    "meal_gallery":          {"he": "גלריית ארוחות",    "en": "Meal Gallery",     "ar": "معرض الوجبات",        "ru": "Галерея блюд"},
    "refer_friend":          {"he": "הזמן חבר — קבל חודש פרמיום!", "en": "Refer a friend — get premium!", "ar": "ادعُ صديقًا — احصل على بريميوم!", "ru": "Пригласи друга — получи премиум!"},
    "loading":               {"he": "טוען...",          "en": "Loading...",       "ar": "جارٍ التحميل...",     "ru": "Загрузка..."},
    "link_whatsapp":         {"he": "חבר WhatsApp לחשבון", "en": "Link WhatsApp", "ar": "ربط واتساب",          "ru": "Привязать WhatsApp"},
    "phone_placeholder":     {"he": "05XXXXXXXX",       "en": "+1XXXXXXXXXX",     "ar": "+9665XXXXXXXX",       "ru": "+7XXXXXXXXXX"},
    "link":                  {"he": "חבר",              "en": "Link",             "ar": "ربط",                 "ru": "Привязать"},
    "sign_out":              {"he": "התנתקות",          "en": "Sign out",         "ar": "تسجيل خروج",          "ru": "Выйти"},
    "dashboard":             {"he": "דשבורד",           "en": "Dashboard",        "ar": "لوحة التحكم",         "ru": "Панель"},
    "chat":                  {"he": "צ׳אט",             "en": "Chat",             "ar": "دردشة",               "ru": "Чат"},
    "daily_insight":         {"he": "תובנה יומית",      "en": "Daily Insight",    "ar": "رؤية يومية",          "ru": "Совет дня"},
    "daily_score":           {"he": "ציון יומי",        "en": "Daily Score",      "ar": "درجة اليوم",          "ru": "Дневной счёт"},
    "protein":               {"he": "חלבון",            "en": "Protein",          "ar": "بروتين",              "ru": "Белок"},
    "carbs":                 {"he": "פחמימות",          "en": "Carbs",            "ar": "كربوهيدرات",          "ru": "Углеводы"},
    "fat":                   {"he": "שומן",             "en": "Fat",              "ar": "دهون",                "ru": "Жиры"},
    "add_glass":             {"he": "הוסף כוס",         "en": "Add glass",        "ar": "أضف كوب",             "ru": "+ стакан"},
    "streak":                {"he": "רצף",              "en": "Streak",           "ar": "سلسلة",               "ru": "Серия"},
    "days":                  {"he": "ימים",             "en": "days",             "ar": "أيام",                "ru": "дней"},
    "protect_streak":        {"he": "הגן על הרצף",      "en": "Protect streak",   "ar": "احمِ السلسلة",        "ru": "Защитить серию"},
    "weight":                {"he": "משקל",             "en": "Weight",           "ar": "الوزن",               "ru": "Вес"},
    "calories_last_7_days":  {"he": "קלוריות — 7 ימים אחרונים", "en": "Calories — Last 7 Days", "ar": "سعرات — آخر 7 أيام", "ru": "Калории — последние 7 дней"},
    "kcal_short":            {"he": "קל",               "en": "kcal",             "ar": "ك.ح",                 "ru": "ккал"},
    "protein_short":         {"he": "חלבון",            "en": "prot",             "ar": "برو",                 "ru": "белок"},
    "carbs_short":           {"he": "פחמ׳",             "en": "carbs",            "ar": "كربو",                "ru": "углев"},
    "fat_short":             {"he": "שומן",             "en": "fat",              "ar": "دهون",                "ru": "жиры"},
    "no_meals_today":        {"he": "עדיין לא דווחו ארוחות היום", "en": "No meals logged today", "ar": "لم يتم تسجيل وجبات اليوم", "ru": "Сегодня блюда не записаны"},
    "quick_actions":         {"he": "פעולות מהירות",    "en": "Quick Actions",    "ar": "إجراءات سريعة",       "ru": "Быстрые действия"},
    "photo_meal":            {"he": "צלם ארוחה",        "en": "Photo Meal",       "ar": "صوّر وجبة",           "ru": "Фото блюда"},
    "barcode":               {"he": "ברקוד",            "en": "Barcode",          "ar": "باركود",              "ru": "Штрихкод"},
    "shopping":              {"he": "קניות",            "en": "Shopping",         "ar": "تسوق",                "ru": "Покупки"},
    "share_story":           {"he": "שתף סיפור",        "en": "Share Story",      "ar": "شارك قصتك",           "ru": "Поделиться историей"},
    "saved_meals":           {"he": "ארוחות שמורות",    "en": "SAVED MEALS",      "ar": "وجبات محفوظة",        "ru": "СОХРАНЁННЫЕ БЛЮДА"},
    "tips_insights":         {"he": "טיפים ותובנות מהתזונאי", "en": "TIPS & INSIGHTS", "ar": "نصائح ورؤى", "ru": "СОВЕТЫ И ИДЕИ"},
    "send_image":            {"he": "שלח תמונה",        "en": "Send image",       "ar": "إرسال صورة",          "ru": "Отправить фото"},
    "voice_input":           {"he": "קלט קולי",         "en": "Voice input",      "ar": "إدخال صوتي",          "ru": "Голосовой ввод"},
    "chat_placeholder":      {"he": "שאל אותי כל דבר, דווח על ארוחה, שלח תמונה...", "en": "Ask anything, log a meal, send a photo...", "ar": "اسألني أي شيء، سجّل وجبة، أرسل صورة...", "ru": "Спросите что угодно, запишите блюдо, отправьте фото..."},
    "weekly_shopping_list":  {"he": "רשימת קניות שבועית","en": "Weekly Shopping List","ar": "قائمة تسوق أسبوعية","ru": "Список покупок на неделю"},
    "copy_list":             {"he": "העתק רשימה",       "en": "Copy List",        "ar": "نسخ القائمة",         "ru": "Копировать"},
    "barcode_scanner":       {"he": "סריקת ברקוד",      "en": "Barcode Scanner",  "ar": "ماسح الباركود",       "ru": "Сканер штрихкода"},
    "add_activity":          {"he": "הוסף פעילות",      "en": "Add Activity",     "ar": "أضف نشاطًا",          "ru": "Добавить активность"},
    "activity_type":         {"he": "סוג פעילות",       "en": "Activity type",    "ar": "نوع النشاط",          "ru": "Тип активности"},
    "duration_min":          {"he": "משך (דקות)",       "en": "Duration (min)",   "ar": "المدة (دقائق)",       "ru": "Длительность (мин)"},
    "calories_burned":       {"he": "קלוריות",          "en": "Calories burned",  "ar": "السعرات المحروقة",    "ru": "Сожжённые калории"},
    "save_activity":         {"he": "שמור פעילות",      "en": "Save Activity",    "ar": "حفظ النشاط",          "ru": "Сохранить активность"},
    "today_plan":            {"he": "תפריט היום",       "en": "Today's Plan",     "ar": "خطة اليوم",            "ru": "План на сегодня"},
    "today_meals":           {"he": "ארוחות היום",      "en": "Today's Meals",    "ar": "وجبات اليوم",          "ru": "Блюда сегодня"},

    # ── JS runtime strings ──
    "shield_already_used":   {"he": "כבר השתמשת במגן החודש הזה", "en": "Already used shield this month", "ar": "لقد استخدمت الدرع هذا الشهر", "ru": "Щит уже использован в этом месяце"},
    "shield_activated":      {"he": "🛡️ המגן הופעל! הרצף שלך מוגן להיום.", "en": "🛡️ Shield activated! Your streak is protected today.", "ar": "🛡️ تم تفعيل الدرع! سلسلتك محمية اليوم.", "ru": "🛡️ Щит активирован! Ваша серия защищена сегодня."},
    "weight_prompt":         {"he": "מה המשקל שלך היום? (קג)", "en": "Your weight today? (kg)", "ar": "ما وزنك اليوم؟ (كغ)", "ru": "Какой ваш вес сегодня? (кг)"},
    "locale_code":           {"he": "he-IL",           "en": "en-US",            "ar": "ar-SA",                "ru": "ru-RU"},
    "connection_error":      {"he": "שגיאת חיבור",     "en": "Connection error", "ar": "خطأ في الاتصال",      "ru": "Ошибка соединения"},
    "no_voice_support":      {"he": "❌ הדפדפן שלך לא תומך בקלט קולי. נסה Chrome.", "en": "❌ Your browser does not support voice input. Try Chrome.", "ar": "❌ متصفحك لا يدعم الإدخال الصوتي. جرّب Chrome.", "ru": "❌ Ваш браузер не поддерживает голосовой ввод. Попробуйте Chrome."},
    "story_copied":          {"he": "📋 הסיפור השבועי הועתק ללוח — תוכל להדביק בWhatsApp!", "en": "📋 Weekly story copied to clipboard — paste it in WhatsApp!", "ar": "📋 تم نسخ القصة الأسبوعية — ألصقها في واتساب!", "ru": "📋 История недели скопирована — вставьте в WhatsApp!"},
    "trimester_1_short":     {"he": "טרימסטר ראשון (שבועות 1-13)", "en": "Trimester 1", "ar": "الثلث الأول (1-13)", "ru": "1-й триместр"},
    "trimester_2_short":     {"he": "טרימסטר שני (שבועות 14-26)", "en": "Trimester 2", "ar": "الثلث الثاني (14-26)", "ru": "2-й триместр"},
    "trimester_3_short":     {"he": "טרימסטר שלישי (שבועות 27-42)", "en": "Trimester 3", "ar": "الثلث الثالث (27-42)", "ru": "3-й триместр"},
    "enter_phone":           {"he": "הכנס מספר טלפון",  "en": "Enter phone number","ar": "أدخل رقم الهاتف",     "ru": "Введите номер телефона"},
    "whatsapp_linked":       {"he": "✅ WhatsApp חובר בהצלחה!", "en": "✅ WhatsApp linked!", "ar": "✅ تم ربط واتساب!", "ru": "✅ WhatsApp привязан!"},
    "generating":            {"he": "מייצר רשימה...",   "en": "Generating...",    "ar": "جارٍ الإنشاء...",     "ru": "Генерация..."},
    "copied":                {"he": "הועתק!",           "en": "Copied!",          "ar": "تم النسخ!",           "ru": "Скопировано!"},
    "waist":                 {"he": "מותניים",          "en": "Waist",            "ar": "الخصر",               "ru": "Талия"},
    "chest":                 {"he": "חזה",              "en": "Chest",            "ar": "الصدر",               "ru": "Грудь"},
    "hips":                  {"he": "ירכיים",           "en": "Hips",             "ar": "الورك",               "ru": "Бёдра"},
    "hello":                 {"he": "שלום!",            "en": "Hello!",           "ar": "مرحبًا!",             "ru": "Привет!"},
    "select_activity":       {"he": "נא לבחור פעילות",  "en": "Please select an activity", "ar": "يرجى اختيار نشاط", "ru": "Пожалуйста, выберите активность"},
    "calories_range_error":  {"he": "קלוריות חייבות להיות בין 1 ל-10000", "en": "Calories must be 1–10000", "ar": "يجب أن تكون السعرات بين 1 و 10000", "ru": "Калории должны быть от 1 до 10000"},
    "duration_range_error":  {"he": "משך חייב להיות בין 0 ל-1440 דקות", "en": "Duration must be 0–1440 min", "ar": "يجب أن تكون المدة بين 0 و 1440 دقيقة", "ru": "Длительность должна быть от 0 до 1440 мин"},
    "trimester_1_long":      {"he": "טרימסטר ראשון (שבועות 1-13)", "en": "Trimester 1 (weeks 1–13)", "ar": "الثلث الأول (الأسابيع 1–13)", "ru": "1-й триместр (недели 1–13)"},
    "trimester_2_long":      {"he": "טרימסטר שני (שבועות 14-26)", "en": "Trimester 2 (weeks 14–26)", "ar": "الثلث الثاني (الأسابيع 14–26)", "ru": "2-й триместр (недели 14–26)"},
    "trimester_3_long":      {"he": "טרימסטר שלישי (שבועות 27-42)", "en": "Trimester 3 (weeks 27–42)", "ar": "الثلث الثالث (الأسابيع 27–42)", "ru": "3-й триместр (недели 27–42)"},

    # ── Placeholder-bearing strings (JS will interpolate {0}/{1}) ──
    "weight_today_msg":      {"he": "המשקל שלי היום {0} קג", "en": "My weight today is {0} kg", "ar": "وزني اليوم {0} كغ", "ru": "Мой вес сегодня {0} кг"},
    "from_start_weight":     {"he": "מ-{0} kg",          "en": "from {0} kg",      "ar": "من {0} كغ",           "ru": "с {0} кг"},
    "streak_amazing":        {"he": "{0} ימים מדהים!",   "en": "{0} amazing days!", "ar": "{0} أيام رائعة!",    "ru": "{0} удивительных дней!"},
    "streak_n_days":         {"he": "{0} ימים ברצף",    "en": "{0} day streak",   "ar": "{0} أيام متتالية",    "ru": "Серия {0} дней"},
}


def get_ui_strings(lang):
    """Return a flat {key: value} dict for the given language.

    Falls back to English for any missing translations.
    """
    if lang not in ("he", "en", "ar", "ru"):
        lang = "en"
    return {k: v.get(lang) or v.get("en") or "" for k, v in UI_STRINGS.items()}
