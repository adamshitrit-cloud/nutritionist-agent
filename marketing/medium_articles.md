# NutriAI — Medium Articles

---

## Article 1

**Title:** Why I Built a WhatsApp Nutritionist Instead of Another App

**Subtitle:** App fatigue is real. The solution isn't a better app — it's no app at all.

**SEO Tags:** nutrition tracking, WhatsApp AI, diet app alternative, habit design, NutriAI, calorie tracking

---

There are over 50,000 health and fitness apps in the App Store. A significant number of them are nutrition trackers. Most of them are beautifully designed, feature-rich, and scientifically grounded. And most people who download them quit within a week.

I know because I was one of those people. Repeatedly.

I've started and abandoned nutrition tracking apps more times than I can count. MyFitnessPal, Cronometer, Lose It, a half-dozen others. The first two or three days always went well. I was motivated. I was logging everything. I was learning things about my diet I hadn't known before.

Then life happened. I'd miss one meal log. Then two. Then I'd open the app five days later, feel the guilt of the gap, and just delete it.

For a long time I thought the problem was willpower. Then I started reading about behavior design, and I realized the problem was friction.

**The real cost of opening an app**

Opening a dedicated app requires a small but real cognitive decision. You have to remember you're tracking. You have to find the app. You have to search for the food — often through a database that doesn't have exactly what you ate. You have to estimate portions. You have to submit the entry. For a single meal, that's two to four minutes and several micro-decisions.

Two to four minutes sounds like nothing. But habits don't fail because of big obstacles. They fail because of small, repeating ones.

**Where people already are**

I started thinking about what behaviors I actually did consistently, without any friction at all. Near the top of the list: WhatsApp. I send and receive messages on WhatsApp dozens of times a day without any deliberate effort. The app is already open. My fingers already know where it is.

What if the nutritionist was just... a contact?

That's the insight behind NutriAI. Instead of asking people to change their behavior — to open a new app, build a new habit, integrate a new tool into their day — it lives inside an existing one. You text it what you ate. You send a photo of your plate. It responds with your calorie count, your macros, your micronutrient tracking, and any flags specific to your dietary mode.

No installation. No onboarding flow. No streak to protect.

**What I learned building it**

The first version took a weekend. Flask backend, Twilio for WhatsApp, Claude AI for the nutritional reasoning. It was rough, but it worked well enough to test.

What surprised me most was engagement. The people I gave early access to weren't more disciplined than average — they were just people who happened to already be on their phone when they ate. The behavior was already there. I had just given it a place to go.

Retention at two weeks is around 60%. For context, most nutrition apps are in the 20–30% range at the same interval. I think the difference is almost entirely behavioral, not feature-based.

**Meet people where they are**

The lesson I keep coming back to is embarrassingly simple: if you want people to do something consistently, put it where they already are. Not where you think they should be, not where it's most technically elegant, not where it's easiest to build — where they actually spend their time.

For a lot of people right now, that's WhatsApp.

NutriAI is free to use at https://nutri-ai.app. Add the number to WhatsApp, tell it your dietary goals, and start texting your meals. No download required.

---

## Article 2

**Title:** The Keto Trap: How AI Can Help You Stay Honest About Your Macros

**Subtitle:** Confirmation bias is the biggest threat to your ketosis — and an AI that doesn't negotiate might be the fix.

**SEO Tags:** keto macro tracker, keto AI, ketogenic diet tracking, keto cheating, keto hidden carbs, AI diet coach

---

There's a pattern I've seen repeatedly in keto communities, and I've lived it myself. Someone posts their food log asking why they're not losing weight. The log looks mostly clean. Then someone in the comments spots it — the "keto-friendly" granola bar, the balsamic glaze, the "just a little" quinoa that appeared three times last week.

The person posting genuinely didn't think those things mattered. Or they found a source that said they didn't. Or they convinced themselves that their version of keto had room for these foods.

This isn't a character flaw. It's confirmation bias operating exactly as designed.

**How we rationalize ourselves out of ketosis**

The human brain is remarkably good at finding reasons why the thing you want to eat is fine. The fitness influencer who said sweet potatoes are "real food." The article that said resistant starch doesn't count. The personal trainer who told you that "a little fruit is okay for active people."

When you're tracking your own food with your own memory and your own judgment, these rationalizations slip through. An app that lets you manually log foods doesn't fight back. It just records what you tell it.

The result is that a lot of people doing "strict keto" are actually doing moderate-low-carb with a story they tell themselves. Which is fine if that's what works for you — but if you're wondering why you're not in ketosis, the answer is often hiding in plain sight.

**The case for an AI that doesn't negotiate**

When I built the keto mode for NutriAI, I made a deliberate design decision: the AI does not validate non-keto foods, regardless of how the user frames them.

If you tell it you had "a small amount of brown rice," it will give you the actual carb count and note that this food is not compatible with ketosis. If you tell it your doctor said oats were fine for your version of keto, it will acknowledge what you've said and still tell you the macros. It doesn't lecture, but it doesn't bend.

I built this to stop gaslighting myself. I tested it against every rationalization I'd ever used and a few I crowdsourced from keto forums. It holds.

**Where hidden carbs actually live**

After analyzing meal logs from NutriAI beta users in keto mode, a few patterns emerged:

- **Sauces and condiments** are the most common source of untracked carbs. Ketchup, barbecue sauce, store-bought salad dressings, teriyaki, and sweet chili sauce can add 10–20g of carbs to a meal that otherwise looks clean.
- **"Keto-friendly" products** are frequently not. Many packaged products marketed to keto dieters use sugar alcohols or fiber claims to advertise a low net carb count, but the total carb count tells a different story.
- **Restaurant meals** are the hardest. Sauces, marinades, and coatings on proteins at restaurants almost always contain sugar. A plain grilled chicken breast is fine; the same chicken in a lemon-butter sauce from most restaurants may not be.
- **Dairy in quantity.** Cheese and cream are keto staples, but portion estimation is where things go wrong. A "handful of cheese" is consistently underestimated by about 40% in self-reported logs.

**Using AI tracking honestly**

A keto macro tracker is only as useful as the honesty you bring to it. But having a system that at least doesn't let you off the hook on the data side removes one variable. You still have to log accurately — but the AI will not help you rationalize what you've logged.

NutriAI's keto mode tracks net carbs, fat-to-protein ratio, and flags any food on the keto blacklist regardless of how it's presented. Photo logging helps with portion estimation, though it's still imperfect on that front.

If you've been doing keto and not seeing results, an honest tracking audit is usually the first place to look. You can try NutriAI at https://nutri-ai.app — start with keto mode and log everything for two weeks without editing.

---

## Article 3

**Title:** Tracking Nutrition During Pregnancy: What Most Apps Get Wrong

**Subtitle:** Pregnancy nutrition is one of the most specific nutritional challenges there is. Generic calorie trackers weren't built for it.

**SEO Tags:** pregnancy nutrition app, what to eat when pregnant, pregnancy diet tracker, folate during pregnancy, iron in pregnancy, food safety pregnancy, AI nutritionist pregnancy

---

When I started looking at how nutrition tracking apps handle pregnancy, I expected to find specialized features. What I found instead was mostly the same calorie counter with a slightly higher daily target and a vague note to talk to your doctor.

This is a real gap. Pregnancy nutrition is not just "eat more calories." It's one of the most specific and high-stakes nutritional situations a person can be in, and the requirements change by trimester, by individual health history, and by pre-existing nutritional status. A generic food log does not capture this.

**What pregnancy nutrition actually requires**

The nutrients that matter most during pregnancy are not the same ones that most tracking apps surface prominently:

- **Folate (and folic acid):** Critical from before conception through the first trimester for neural tube development, and important throughout. Most apps track it, but few flag deficiency proactively or explain the difference between folate from food and folic acid from supplements.
- **Iron:** Needs roughly double during pregnancy due to increased blood volume. Non-heme iron from plants is significantly less bioavailable than heme iron from meat, a distinction that most apps ignore entirely when they calculate whether you've "hit your iron goal."
- **Calcium and vitamin D:** Fetal bone development draws heavily from maternal stores. Low intake doesn't produce symptoms in the mother — it silently depletes her bones.
- **Choline:** Emerging research links choline intake during pregnancy to fetal brain development. Almost no mainstream tracking app surfaces this.
- **Omega-3 DHA:** Important for fetal neurological development, but the source matters — not all omega-3s are equivalent, and some fish high in omega-3s are also high in mercury.

**The food safety dimension**

Pregnancy introduces a set of foods that are not just "less healthy" but actively dangerous at the wrong moment. Listeria, toxoplasma, and high mercury exposure carry real risks to fetal development. The list of foods to avoid is not intuitive:

- Deli meats (listeria risk unless heated)
- Soft cheeses and unpasteurized dairy
- Raw or undercooked eggs, meat, and seafood
- High-mercury fish: swordfish, king mackerel, tilefish, shark, and — at moderate frequency — albacore tuna
- Raw sprouts
- Unpasteurized juices

Most calorie tracking apps do not flag these foods at all. You find out about them from a pamphlet at your OB's office, a forum post, or by luck.

**What a pregnancy-specific nutrition tool should do**

When building the pregnancy mode for NutriAI, the goal was to address these gaps specifically:

1. **Track the right nutrients** — folate, iron (with a note on absorption differences), calcium, vitamin D, choline, and omega-3s, not just protein and calories.
2. **Flag food safety risks with explanations** — not a binary "avoid this" but "this carries listeria risk unless heated to 165°F, here's why."
3. **Adjust for trimester** — caloric and nutritional needs shift. A first trimester user and a third trimester user have different targets.
4. **Provide context** — iron from spinach is different from iron from red meat. The AI explains these distinctions when they're relevant rather than just giving a raw number.

**The conversation format advantage**

One thing that's harder to capture in a traditional app but works naturally in a conversational AI: follow-up questions. "Is canned tuna okay?" gets a nuanced answer — light tuna in moderation is generally considered acceptable, albacore less so. "Can I eat sushi?" depends on the type of sushi. These questions have answers that require context, and a chat interface handles them better than a food database lookup.

NutriAI's pregnancy mode is available now at https://nutri-ai.app. It works via WhatsApp — no app download. If you're pregnant or planning to be, it's designed to surface the information that actually matters for this specific stage, not just a calorie count.

---

## Article 4

**Title:** I Analyzed 1,000 Meal Logs. Here's What People Actually Eat on Keto.

**Subtitle:** The data from a year of AI-powered keto tracking reveals patterns that no one in the keto community talks about.

**SEO Tags:** keto mistakes, keto hidden carbs, keto meal tracking data, keto plateau, what to eat on keto, keto food log analysis, keto AI tracker

---

When you ask someone on keto what they eat, you get the highlight reel: steak, eggs, avocado, bacon, cheese, leafy greens. Clean, simple, high-fat.

When you look at what they actually log over six months, the picture is more complicated.

After analyzing over 1,000 meal logs from NutriAI users in keto mode, a few patterns emerged that I think will resonate with anyone who's hit a plateau or wondered why their ketosis doesn't look like the person's on the subreddit.

**Finding 1: People underestimate condiments by a factor of three**

In self-reported logs, condiment portions are almost always listed as "small amount" or not listed at all. When users were asked to photo-log the same meal instead of typing it, the AI identified sauces and condiments in 67% of meals that had been logged as sauce-free.

The carb count in condiments adds up fast. A tablespoon of ketchup has 4g of carbs. A packet of barbecue sauce at a restaurant can have 12–15g. Teriyaki, honey mustard, sweet chili sauce, and many "light" salad dressings all carry significant sugar. For someone targeting 20g net carbs per day, condiments can represent 25–50% of their daily carb budget without their knowledge.

**Finding 2: "Keto-friendly" products are the second-biggest source of hidden carbs**

Packaged foods marketed as keto-friendly are a significant source of over-limit days in the data. The pattern is consistent: users log a "keto" protein bar, a "low-carb" wrap, or a "keto" granola cluster, confident that the marketing guarantees compliance.

In 43% of these cases, when the AI pulled actual label data, the product exceeded 5g net carbs per serving — and actual serving sizes consumed were frequently 1.5x to 2x the listed serving size.

The problem is partly that "net carb" calculations on packaged foods are inconsistent and sometimes misleading. Some manufacturers subtract all fiber from total carbs regardless of fermentability. Some use sugar alcohol counts that don't hold up in practice for people who are metabolically sensitive.

**Finding 3: Protein is frequently over-consumed, but nobody is worried about it**

The keto community's discourse is heavily focused on carbs, as it should be — carb intake is the primary lever for ketosis. But in the meal logs, protein overconsumption appeared in roughly 38% of daily logs.

This matters because excess protein can undergo gluconeogenesis — the liver converts it to glucose, which can suppress ketosis. The threshold varies by individual, but a consistent pattern of 180–200g+ of protein daily from users who are not highly active showed up frequently enough to note.

Most people doing keto are not tracking protein targets as closely as carb targets. The AI flags this by default in keto mode, and it's consistently one of the more surprising pieces of feedback users receive.

**Finding 4: Meal timing clusters at the extremes**

Keto users in the data tend to eat either very early (breaking fast before 9am) or skip breakfast entirely. This is not surprising given the overlap between keto and intermittent fasting communities. What is interesting is that the distribution of meal timing correlates with reported energy levels in user check-ins.

Users who ate within two hours of waking reported afternoon energy crashes at roughly 2.4x the rate of users who delayed their first meal by three or more hours. This is self-reported and correlational, not causal — but the pattern was consistent enough to mention.

**Finding 5: Plateaus almost always have a traceable explanation**

When users reported a keto plateau in their check-in messages and we reviewed the prior four weeks of logs, 81% had an identifiable dietary contributor: a period of elevated condiment carbs, a run of "keto-friendly" packaged foods, a stretch of high protein intake, or gradual serving size creep on high-fat foods that had increased total caloric intake.

The remaining 19% had clean logs and may have been experiencing genuine metabolic adaptation, hormonal factors, or logging accuracy issues that the AI couldn't capture.

**What this means practically**

If you're on keto and not seeing the results you expect, the most likely explanations — in order of frequency from this data — are:

1. Condiments and sauces you're not counting
2. Packaged "keto" products with higher net carbs than labeled
3. Protein intake high enough to affect ketosis
4. Gradual caloric creep on fat intake
5. Actual metabolic adaptation (the least common and most often blamed)

Photo logging catches more of issues 1 and 4 than text logging does. A stricter approach to packaged foods resolves 2. Explicit protein targets help with 3.

NutriAI tracks all of these in keto mode, flags the patterns automatically, and surfaces them in your weekly summary. You can start tracking at https://nutri-ai.app via WhatsApp — no app download required.
