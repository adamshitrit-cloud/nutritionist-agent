# NutriAI — Product Hunt Screenshots Brief

> **Technical specs:** Minimum 1270×952px. PNG preferred. Use a clean device mockup frame (iPhone or browser chrome). Keep UI uncluttered — remove test data, use realistic but photogenic meal names.
>
> **Order matters.** Screenshot 1 is the most important — it's the thumbnail shown in the PH feed. Make it work as a standalone visual even without reading the caption.

---

## Screenshot 1 — The Hero Shot (Most Important)

**What to show:**
A side-by-side split: on the left, a WhatsApp conversation with NutriAI. On the right, the web dashboard showing the day's nutrition summary. Both panels should look polished and populated with real data.

**WhatsApp conversation content to display:**
```
User: [photo of a salad with grilled chicken]
NutriAI: Great choice! I analyzed your meal:
  🥗 Grilled Chicken Salad
  Calories: 420 kcal
  Protein: 38g  |  Carbs: 12g  |  Fat: 18g
  You're at 1,240 / 1,800 kcal today. On track! 💪
```

**Dashboard panel content:**
Show today's ring/progress bars at roughly 70% full — not empty (looks unused) and not overflowing (looks alarming). Include a daily streak number (e.g., "Day 14").

**Caption:**
> Your AI nutritionist lives in WhatsApp — snap a photo, get instant nutrition data. No app download needed.

**UI state:** Mid-day, logged 3 meals already, healthy progress toward daily goal.

---

## Screenshot 2 — Food Photo Recognition

**What to show:**
A WhatsApp conversation where the user sent a food photo and NutriAI returned a detailed breakdown. Use a visually appealing food — a colorful grain bowl, avocado toast, or shakshuka works well.

**Conversation content to display:**
```
User: [photo of avocado toast with egg]
NutriAI: Logged! Here's what I see:
  🥑 Avocado Toast with Poached Egg (sourdough)
  Calories: 380 kcal
  Protein: 16g  |  Carbs: 34g  |  Fat: 21g  |  Fiber: 7g

  Healthy fats looking good. This fits your 
  Mediterranean plan perfectly. ✅
```

**Caption:**
> Just snap a photo. NutriAI identifies your meal and logs the macros automatically — no typing, no searching.

**UI state:** Single message exchange. Keep it tight so the full conversation is visible without scrolling.

---

## Screenshot 3 — Multi-Diet Mode Selection

**What to show:**
The web UI's diet mode selector or a WhatsApp conversation where the user switches to Keto mode and NutriAI confirms with a keto-specific response. If showing the web UI, display the four mode cards (Keto, Mediterranean, Intermittent Fasting, Pregnancy) with Keto currently selected.

**If showing WhatsApp conversation:**
```
User: Switch me to keto mode
NutriAI: Done! Keto mode is now active. 🥑
  Your new daily targets:
  • Net carbs: ≤ 20g (strict)
  • Fat: 140g  |  Protein: 100g
  • Calories: 1,800 kcal

  I'll flag any food that could break ketosis — 
  even hidden carbs in sauces and dressings. 
  Want to log your first keto meal?
```

**Caption:**
> Keto, Mediterranean, Intermittent Fasting, or Pregnancy mode — switch anytime. Each mode adjusts your targets and coaching style.

**UI state:** Mode just switched, fresh targets displayed.

---

## Screenshot 4 — Pregnancy Mode (Unique Differentiator)

**What to show:**
A WhatsApp conversation showing NutriAI's pregnancy-aware coaching. The AI should be flagging an unsafe food or proactively tracking a pregnancy-critical nutrient (folate, iron).

**Conversation content to display:**
```
User: I had sushi for lunch — tuna roll and salmon roll
NutriAI: Heads up! 🤰 In pregnancy mode, I watch 
  for high-mercury fish.
  
  Tuna (especially bluefin) carries mercury risk 
  in pregnancy. Salmon is generally safer — good 
  choice there.

  Today's nutrient check:
  Folate: 280mcg / 600mcg daily goal
  Iron: 14mg / 27mg daily goal
  
  Tip: Add lentils or spinach tonight to boost 
  your iron. Want a quick recipe idea?
```

**Caption:**
> Pregnancy mode tracks folate, iron & calcium — and flags foods that aren't safe during pregnancy. Built for expecting moms.

**UI state:** NutriAI has just responded to a meal log with safety guidance. No alarming red colors — warm, supportive tone.

---

## Screenshot 5 — Weekly Summary & Insights

**What to show:**
Either the web UI's weekly chart view (showing calorie trend over 7 days, macro breakdown pie chart) OR a WhatsApp conversation showing NutriAI's weekly summary response.

**If showing WhatsApp conversation:**
```
User: How did I do this week?
NutriAI: Here's your week at a glance 📊
  
  ✅ Hit your calorie goal: 5 of 7 days
  ✅ Protein avg: 112g/day (target: 100g) — great!
  ⚠️ Carbs ran high Wednesday & Thursday
  💧 Hydration: logged 3 of 7 days — try to track 
     more consistently
  
  Overall: Strong week! Your best day was Tuesday.
  
  Top suggestion: Watch the evening snacks — that's 
  where your carbs spiked both days. Want me to 
  suggest some swaps?
```

**Caption:**
> Ask "how did I do this week?" and get a real answer — trends, patterns, and personalized suggestions to keep improving.

**UI state:** End of week, mixed results (realistic — not perfect, not terrible). This feels authentic.

---

## Production Notes

- Use iPhone 14/15 mockup frame for WhatsApp screenshots — it's the most universally recognizable
- For web UI screenshots, use a browser frame (Chrome) at MacBook or wide-screen dimensions
- Keep font sizes legible at thumbnail size — zoom in on the conversation if needed
- Consistent color scheme across all screenshots: use NutriAI's brand colors for any overlaid captions
- Add a subtle drop shadow to device mockups — lifts them off the background
- Recommended background colors: clean white (#FFFFFF), light gray (#F5F5F5), or a soft green (#E8F5E9) that evokes health/nutrition
- Overlay caption text in a bold, readable sans-serif font at the bottom of each screenshot (not inside the device frame)
- Test all screenshots at 40% scale — this is approximately how they appear in the PH feed
