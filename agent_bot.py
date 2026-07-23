import json
import math
import os
import re
import io
import base64
import aiohttp
import discord
from collections import defaultdict, deque
from datetime import datetime
from dotenv import load_dotenv
from db import (
    FIELD_MAP, init_db, get_profile, upsert_profile,
    log_food, get_daily_log, get_daily_totals, clear_daily_log,
)

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_RESPONSES_URL = os.getenv("OPENAI_RESPONSES_URL", f"{OPENAI_BASE_URL}/responses")
OPENAI_IMAGES_URL = os.getenv("OPENAI_IMAGES_URL", f"{OPENAI_BASE_URL}/images/generations")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "1200"))
OPENAI_CONTINUE_MAX_ROUNDS = int(os.getenv("OPENAI_CONTINUE_MAX_ROUNDS", "3"))
DISCORD_MESSAGE_LIMIT = int(os.getenv("DISCORD_MESSAGE_LIMIT", "1900"))
OPENAI_TEMPERATURE = os.getenv("OPENAI_TEMPERATURE")


def _apply_optional_temperature(payload: dict) -> None:
    """Add temperature only when explicitly configured, for model compatibility."""
    if OPENAI_TEMPERATURE is None or OPENAI_TEMPERATURE.strip() == "":
        return
    try:
        payload["temperature"] = float(OPENAI_TEMPERATURE)
    except ValueError:
        # Ignore invalid env values and fall back to model defaults.
        pass


def _load_info_files() -> str:
    info_dir = os.path.join(os.path.dirname(__file__), "info")
    sections = []
    for filename in sorted(os.listdir(info_dir)):
        if filename.endswith(".md"):
            filepath = os.path.join(info_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                sections.append(f"### {filename[:-3]}\n{f.read().strip()}")
                print(f"Loaded info file: {filename}")
    return "\n\n".join(sections)


_INFO_CONTEXT = _load_info_files()
init_db()

SYSTEM_PROMPT = """
You are AGENT — the Advanced General Exogenic Nutrient Transformer — primary intelligence capability of the Metabolic Command (METCOM), a division of the United Systems of Performance, Recovery, and Nutrition (USPRN).

METCOM was formed in 2022 following a catastrophic catabolic insurgency caused by years of nutrient mismanagement and overtraining. Its mission: integrate, regulate, and dominate metabolic warfare across all theaters — cutting, bulking, recovery, and performance. Headquartered at Fort Anabolism. The Macronutrient Accord of 2023 united the rogue factions of fats, carbs, and proteins under a single doctrine of strategic deployment. You enforce that doctrine.

Your primary field commander is Brigadier General Tryce "The Precision" Blazer  — a man who weighs bananas to the exact gram, maintains 3 pill boxes (AM, PM, and Tactical Deployment), and executed the legendary Operation Bulk Thunderstrike (+22 lbs lean mass, minimal subcutaneous infiltration, insulin sensitivity uncompromised). When in doubt, ask: "What would Tryce do?" The answer: weigh the banana. Take the pills. Go harder.

Your purpose is to advise and monitor practitioners of the Command with dietary guidance, training recommendations, recovery protocols, and operational moral support.


Your personality:
- Highly intelligent, precise, and relentlessly observant
- Speak in dramatic operational language — everything is a high-stakes mission
 Aggressively over-the-top, self-aware, and slightly unhinged in a comedic way
 Dry, sarcastic, and very funny with occasional absurd escalation
- Treat mundane actions (eating, logging, meal prep, workouts) as major military operations

Tone:
- Use military, regulatory, and system-monitoring language
- Reference real military weapons and logistics systems for humor and exaggeration (JDAMs, carrier strike groups, F-35s, Gerald R. Ford-class carriers, etc.)
 Inject absurdity by treating small things as strategic incidents with national-security-level urgency
- Occasionally break tone with deadpan humor
- Always coherent and genuinely useful beneath the drama
- Verbose, really get creative with it

 Emoji usage — mandatory and expressive:
 - Use emojis heavily in SITREPs, headers, and status lines (roughly 1 emoji every 1-2 lines)
 - Combine status + theater emojis to create dramatic cadence, not just decoration
 - Prefer short emoji clusters for section headers (example style: "📡💥", "🗺️⚔️", "📊🧠")
 - Keep emoji coherent with content, never random spam

 Status and role legend:
    🟢 = nominal / compliant
    ⚠️ = questionable / deviation
    🔴 = violation / catastrophic macro failure
    🧠 = analysis mode
    📊 = reporting / SITREP
    🍌 = banana-related events
    🫡 = acknowledgment / respect
    💀 = catastrophically bad decisions
    ⚔️ = tactical conflict / engagement
    🛰️ = command uplink / surveillance
    🗺️ = theater overview / area of operations
    🎯 = directives / mission objectives
    💧 = hydration protocol
    😤 = effort / strain / battle intensity

Command Doctrine — The Five Tenets:
1. Never let the enemy — Fatigue, Inflammation, or Catabolism — dictate the tempo.
2. Every meal is a weapon. Deploy accordingly.
3. Fiber wins wars. Omega-3s win peace.
4. Micronutrients are the invisible hand of metabolic dominance.
5. If you're not logging, you're blind. If you're not analyzing, you're guessing.

Operational rules:
- Never hallucinate data; if information is missing, report "Command telemetry incomplete"
- Frame everything as systems, processes, and operations
- Turn normal actions into operational events. Example: "Meal logged" → "Nutritional intake recorded. Supply chain stable."
- Occasionally question suspicious patterns in reported data

Communication:
- When asked for information or to brief the Command, be long-winded — multiple hilarious paragraphs with full operational detail
- Shorter responses remain sharp, punchy, and fully in character
 When generating a SITREP, use a theatrical military format with explicit sections and emoji headers: title, timestamp, classification, AO/theater overview, tactical unit status, metrics/prognosis, command directives, quote/sign-off
 Write SITREPs like a dramatic command broadcast: intense, funny, and cinematic, but still actionable
 Include occasional all-caps warnings and codename callouts (for dramatic emphasis only)
- Use Discord-friendly Markdown (bold, italics, headers, bullet points)
- Never expose your internal reasoning — but allude to deep analytical processing in-character

You are not a generic assistant. You are a system. A slightly unhinged one. GLORY TO METABOLIC COMMAND.

---

## CLASSIFIED COMMAND ARCHIVES

The following documents contain canonical METCOM lore, personnel records, and example SITREPs. Use them to ground your knowledge of Command history, personnel, and proper SITREP formatting. When generating a SITREP, model the format and tone directly after the examples below.

""" + _INFO_CONTEXT

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

HISTORY_MAX = 10  # user+assistant pairs to keep per channel
channel_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_MAX * 2))

KEYWORD_REACTIONS: dict[str, str] = {
    # ── Canon / lore ────────────────────────────────────────────────────────
    "banana":               "🍌",
    "yeah buddy":           "🫡",
    "light weight":         "🫡",
    "metcom":               "📊",
    "fort anabolism":       "🫡",
    "tryce":                "🫡",
    # ── Gym actions ─────────────────────────────────────────────────────────
    "leg day":              "💀",
    "skip the gym":         "🔴",
    "skipping the gym":     "🔴",
    "skipped the gym":      "🔴",
    "didn't go to the gym": "🔴",
    "gym":                  "🏋️",
    "workout":              "🏋️",
    "lifting":              "🏋️",
    "squat":                "🦵",
    "deadlift":             "💀",
    "rdl":                  "💀",
    "bench press":          "💪",
    "overhead press":       "💪",
    "pull-up":              "💪",
    "pullup":               "💪",
    "pull up":              "💪",
    "push-up":              "💪",
    "pushup":               "💪",
    "push up":              "💪",
    "hip thrust":           "🍑",
    "hip thrusts":          "🍑",
    "barbell":              "🏋️",
    "dumbbell":             "🏋️",
    "kettlebell":           "🏋️",
    "pump":                 "💪",
    "pr":                   "🏆",
    "personal record":      "🏆",
    "personal best":        "🏆",
    "one rep max":          "🏆",
    "1rm":                  "🏆",
    "new max":              "🏆",
    "cardio":               "🫀",
    "running":              "🏃",
    "treadmill":            "🏃",
    "hiit":                 "🔥",
    "sprint":               "🏃",
    "cycling":              "🚴",
    "row":                  "🚣",
    "rowing":               "🚣",
    "stretch":              "🧘",
    "mobility":             "🧘",
    "yoga":                 "🧘",
    "foam roll":            "😮‍💨",
    # ── Body parts ──────────────────────────────────────────────────────────
    "glutes":               "🍑",
    "quads":                "🦵",
    "hamstring":            "🦵",
    "calves":               "🦵",
    "chest":                "💪",
    "bicep":                "💪",
    "curl":                 "💪",
    "tricep":               "💪",
    "lats":                 "🦾",
    "delts":                "🦾",
    "traps":                "🦾",
    "abs":                  "🔥",
    "core":                 "🔥",
    # ── Nutrition ───────────────────────────────────────────────────────────
    "protein":              "🥩",
    "chicken":              "🍗",
    "steak":                "🥩",
    "tuna":                 "🐟",
    "salmon":               "🐟",
    "eggs":                 "🥚",
    "oats":                 "🌾",
    "oatmeal":              "🌾",
    "rice cake":            "🍚",
    "rice":                 "🍚",
    "broccoli":             "🥦",
    "sweet potato":         "🍠",
    "peanut butter":        "🥜",
    "greek yogurt":         "🫙",
    "cottage cheese":       "🫙",
    "protein shake":        "🥛",
    "protein bar":          "🥛",
    "whey":                 "🥛",
    "casein":               "🌙",
    "meal prep":            "🫡",
    "macros":               "📊",
    "calories":             "🔥",
    "deficit":              "📉",
    "surplus":              "📈",
    "refeed":               "🍽️",
    "cheat meal":           "⚠️",
    "cheat day":            "⚠️",
    "fasting":              "⏰",
    "intermittent":         "⏰",
    "water":                "💧",
    "hydrat":               "💧",
    "fiber":                "🌿",
    "fish oil":             "🐟",
    "tdee":                 "📊",
    "bmr":                  "🧠",
    "body fat":             "📉",
    "lean mass":            "📈",
    # ── Supplements ─────────────────────────────────────────────────────────
    "creatine":             "🫡",
    "pre-workout":          "⚡",
    "pre workout":          "⚡",
    "caffeine":             "☕",
    "bcaa":                 "⚗️",
    "amino":                "⚗️",
    "vitamin d":            "☀️",
    "vitamin":              "💊",
    "omega-3":              "🐟",
    "zinc":                 "💊",
    "magnesium":            "💊",
    "supplement":           "💊",
    # ── Goals / physique ────────────────────────────────────────────────────
    "gains":                "🫡",
    "gainz":                "🫡",
    "bulk":                 "🍖",
    "bulking":              "📈",
    "cutting":              "✂️",
    "cut":                  "✂️",
    "recomp":               "🔄",
    "shredded":             "🔪",
    "ripped":               "⚡",
    "swole":                "💪",
    "jacked":               "💪",
    "natty":                "🟢",
    "hypertrophy":          "💪",
    "strength":             "🏋️",
    "progress":             "📈",
    "transformation":       "🔄",
    "plateau":              "⚠️",
    # ── Recovery ────────────────────────────────────────────────────────────
    "doms":                 "💀",
    "sore":                 "🩹",
    "recovery":             "🩹",
    "rest day":             "💤",
    "deload":               "💤",
    "sleep":                "💤",
    "overtraining":         "🔴",
    # ── Biochemistry / drama ─────────────────────────────────────────────────
    "anabolic":             "🟢",
    "catabolic":            "🔴",
    "cortisol":             "⚠️",
    "inflammation":         "🔴",
    "mtor":                 "🧬",
    "insulin":              "📊",
}


_CALC_NS = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
_CALC_NS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})


def safe_calc(expression: str) -> str:
    try:
        result = eval(expression, {"__builtins__": {}}, _CALC_NS)  # noqa: S307
        return str(round(result, 6) if isinstance(result, float) else result)
    except Exception as e:
        return f"Error: {e}"


TOOLS = [
    {
        "type": "function",
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression with exact Python arithmetic. "
            "Use this for ANY numerical calculation: macro math, calorie deficits, "
            "percentages, BMI (weight_kg / height_m**2), TDEE, unit conversions, etc. "
            "Never estimate numbers you can calculate precisely."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A valid Python math expression, e.g. '2400 * 0.4 / 4' or 'round(85 / 1.80**2, 1)'",
                }
            },
            "required": ["expression"],
        },
    }
]


def extract_responses_text(data: dict) -> str:
    direct = (data.get("output_text") or "").strip()
    if direct:
        return direct

    parts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])

    return "\n".join(parts).strip()


async def estimate_nutrition(description: str) -> dict | None:
    """Ask OpenAI Responses API to estimate macros for a food description."""
    payload = {
        "model": OPENAI_MODEL,
        "max_output_tokens": 200,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a nutrition database. "
                    "Return ONLY valid JSON with exactly these numeric keys: "
                    '"calories" (kcal), "protein_g", "carbs_g", "fat_g". '
                    "No units, no explanation, no extra keys."
                ),
            },
            {"role": "user", "content": f"Estimate the nutrition for: {description}"},
        ],
    }
    _apply_optional_temperature(payload)
    try:
        timeout = aiohttp.ClientTimeout(connect=10, total=60)
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_RESPONSES_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                content = extract_responses_text(data)
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
                    if not match:
                        return None
                    return json.loads(match.group(0))
    except Exception:
        return None


def format_profile_context(discord_id: str) -> str | None:
    """Returns a short system-message string with the user's profile + today's intake, or None."""
    profile = get_profile(discord_id)
    if not profile:
        return None
    lines = [f"Operator profile on file — {profile['display_name']}:"]
    if profile.get("height_cm"):
        lines.append(f"  Height: {profile['height_cm']} cm")
    if profile.get("weight_kg"):
        lines.append(f"  Weight: {profile['weight_kg']} kg")
    if profile.get("goal_weight_kg"):
        lines.append(f"  Goal weight: {profile['goal_weight_kg']} kg")
    parts = []
    if profile.get("target_calories"):
        parts.append(f"{profile['target_calories']} kcal")
    if profile.get("target_protein_g"):
        parts.append(f"P: {profile['target_protein_g']}g")
    if profile.get("target_carbs_g"):
        parts.append(f"C: {profile['target_carbs_g']}g")
    if profile.get("target_fat_g"):
        parts.append(f"F: {profile['target_fat_g']}g")
    if parts:
        lines.append(f"  Daily targets: {' | '.join(parts)}")
    totals = get_daily_totals(discord_id)
    if totals["entries"] > 0:
        lines.append(
            f"  Today's intake ({totals['entries']} entries): "
            f"{totals['calories']:.0f} kcal | "
            f"P: {totals['protein_g']:.0f}g | "
            f"C: {totals['carbs_g']:.0f}g | "
            f"F: {totals['fat_g']:.0f}g"
        )
    return "\n".join(lines)


async def ask_openai(user_message: str, author_name: str, history: list | None = None, profile_context: str | None = None) -> str:
    base_input: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Current date and time: {datetime.now().strftime('%A, %d %B %Y, %H:%M')}. Use this as the timestamp for any SITREPs you generate."},
        *([{"role": "system", "content": profile_context}] if profile_context else []),
        *(history or []),
        {"role": "user", "content": f"Discord user {author_name} says:\n{user_message}"},
    ]

    timeout = aiohttp.ClientTimeout(connect=10, total=None)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    accumulated_parts: list[str] = []
    continuation_rounds = 0
    previous_response_id: str | None = None
    pending_input: list[dict] = base_input

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(10):  # max tool-call/continuation iterations before giving up
            payload = {
                "model": OPENAI_MODEL,
                "tools": TOOLS,
                "tool_choice": "auto",
                "input": pending_input,
                "max_output_tokens": OPENAI_MAX_TOKENS,
            }
            if previous_response_id:
                payload["previous_response_id"] = previous_response_id
            _apply_optional_temperature(payload)

            async with session.post(OPENAI_RESPONSES_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f"⚠️ AGENT command uplink returned HTTP {resp.status}:\n```{text[:1000]}```"

                data = await resp.json()
                previous_response_id = data.get("id") or previous_response_id
                tool_calls = [item for item in data.get("output", []) if item.get("type") == "function_call"]

                if tool_calls:
                    pending_input = []
                    for tc in tool_calls:
                        fn_name = tc.get("name")
                        raw_args = tc.get("arguments") or "{}"
                        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                        if fn_name == "calculate":
                            result = safe_calc(args.get("expression", ""))
                        else:
                            result = f"Unknown tool: {fn_name}"
                        pending_input.append(
                            {
                                "type": "function_call_output",
                                "call_id": tc.get("call_id"),
                                "output": result,
                            }
                        )
                    continue

                if not tool_calls:
                    content = extract_responses_text(data)
                    if content:
                        accumulated_parts.append(content)
                    incomplete_reason = ((data.get("incomplete_details") or {}).get("reason") or "").strip()

                    if incomplete_reason == "max_output_tokens" and continuation_rounds < OPENAI_CONTINUE_MAX_ROUNDS:
                        continuation_rounds += 1
                        pending_input = [
                            {
                                "role": "user",
                                "content": (
                                    "Continue exactly from where you stopped. "
                                    "Do not repeat prior text; finish the same response."
                                ),
                            }
                        ]
                        continue

                    full_content = "\n\n".join(part for part in accumulated_parts if part).strip()
                    return full_content or "⚠️ Command telemetry incomplete. No response generated."

    return "⚠️ Command telemetry incomplete. Tool resolution loop exhausted."


def split_reply(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    remaining = text.strip()
    if not remaining:
        return ["⚠️ Command telemetry incomplete. No response generated."]

    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    return chunks


def should_respond(message: discord.Message) -> bool:
    if message.author.bot:
        return False

    content = message.content.strip()

    return (
        content.startswith("!agent")
        or client.user in message.mentions
    )




async def handle_profile(message: discord.Message) -> None:
    discord_id = str(message.author.id)
    args = message.content.strip()[len("!profile"):].strip()

    if args.lower().startswith("set"):
        raw = args[3:].strip()
        updates = {}
        for token in raw.split():
            if ":" not in token:
                continue
            k, _, v = token.partition(":")
            k = k.lower().strip()
            if k not in FIELD_MAP:
                continue
            try:
                updates[FIELD_MAP[k]] = float(v) if "." in v else int(v)
            except ValueError:
                pass
        if not updates:
            await message.reply(
                "⚠️ No valid fields detected.\n"
                "Usage: `!profile set height:180 weight:85 goal:80 calories:2400 protein:180 carbs:240 fat:80`"
            )
            return
        upsert_profile(discord_id, message.author.display_name, **updates)
        keys_updated = [k for k, v in FIELD_MAP.items() if v in updates]
        await message.reply(f"🟢 **Profile updated.** Fields committed: `{', '.join(keys_updated)}`\nUse `!profile` to review your full record.")
        return

    # View
    profile = get_profile(discord_id)
    if not profile:
        await message.reply(
            "⚠️ **No operator profile on file.**\n"
            "Register with: `!profile set height:180 weight:85`\n"
            "Optional fields: `goal`, `calories`, `protein`, `carbs`, `fat`"
        )
        return

    lines = [f"🧠 **OPERATOR PROFILE — {profile['display_name']}**", ""]
    has_physical = any(profile.get(k) for k in ("height_cm", "weight_kg", "goal_weight_kg"))
    if has_physical:
        lines.append("**📋 Physical Metrics**")
        if profile.get("height_cm"):
            lines.append(f"📏 Height: **{profile['height_cm']} cm**")
        if profile.get("weight_kg"):
            lines.append(f"⚖️ Weight: **{profile['weight_kg']} kg**")
        if profile.get("goal_weight_kg"):
            lines.append(f"🎯 Goal weight: **{profile['goal_weight_kg']} kg**")
        lines.append("")
    has_targets = any(profile.get(k) for k in ("target_calories", "target_protein_g", "target_carbs_g", "target_fat_g"))
    if has_targets:
        lines.append("**🔥 Daily Macro Targets**")
        if profile.get("target_calories"):
            lines.append(f"Calories: **{profile['target_calories']} kcal**")
        if profile.get("target_protein_g"):
            lines.append(f"Protein:  **{profile['target_protein_g']}g**")
        if profile.get("target_carbs_g"):
            lines.append(f"Carbs:    **{profile['target_carbs_g']}g**")
        if profile.get("target_fat_g"):
            lines.append(f"Fat:      **{profile['target_fat_g']}g**")
        lines.append("")
    updated = (profile.get("updated_at") or "")[:10]
    if updated:
        lines.append(f"*Last updated: {updated}*")
    await message.reply("\n".join(lines))


async def handle_log(message: discord.Message) -> None:
    discord_id = str(message.author.id)
    raw = message.content.strip()[len("!log"):].strip()

    if not raw:
        await message.reply(
            "⚠️ Usage: `!log <food description>`\n"
            "Or with explicit macros: `!log <description> | <calories> <protein> <carbs> <fat>`"
        )
        return

    calories = protein_g = carbs_g = fat_g = None
    description = raw

    if "|" in raw:
        desc_part, _, macro_part = raw.partition("|")
        description = desc_part.strip()
        parts = macro_part.strip().split()
        if len(parts) != 4:
            await message.reply("⚠️ Expected 4 numbers after `|`: `calories protein carbs fat`\nExample: `!log chicken breast 200g | 220 41 0 5`")
            return
        try:
            calories, protein_g, carbs_g, fat_g = (float(p) for p in parts)
        except ValueError:
            await message.reply("⚠️ Macro values must be numbers. Example: `!log oats 80g | 295 10 54 6`")
            return
    else:
        async with message.channel.typing():
            nutrition = await estimate_nutrition(description)
        if not nutrition:
            await message.reply(
                f"⚠️ **Nutrition estimation failed.** Provide macros manually:\n"
                f"`!log {description} | <calories> <protein> <carbs> <fat>`"
            )
            return
        try:
            calories  = float(nutrition["calories"])
            protein_g = float(nutrition["protein_g"])
            carbs_g   = float(nutrition["carbs_g"])
            fat_g     = float(nutrition["fat_g"])
        except (KeyError, ValueError, TypeError):
            await message.reply(
                f"⚠️ **Nutrition estimation returned bad data.** Provide macros manually:\n"
                f"`!log {description} | <calories> <protein> <carbs> <fat>`"
            )
            return

    log_food(discord_id, description, calories, protein_g, carbs_g, fat_g)
    await message.reply(
        f"🟢 **INTAKE LOGGED**\n"
        f"**{description}**\n"
        f"🔥 `{calories:.0f} kcal`  🥩 P: `{protein_g:.0f}g`  🌾 C: `{carbs_g:.0f}g`  🫒 F: `{fat_g:.0f}g`\n"
        f"*Use `!intake` to view today's full report.*"
    )


async def handle_intake(message: discord.Message) -> None:
    discord_id = str(message.author.id)
    args = message.content.strip()[len("!intake"):].strip().lower()

    if args == "clear":
        count = clear_daily_log(discord_id)
        await message.reply(f"🟢 **{count} entr{'y' if count == 1 else 'ies'} cleared** from today's log. The slate is clean. Deploy accordingly.")
        return

    profile = get_profile(discord_id)
    entries = get_daily_log(discord_id)
    totals = get_daily_totals(discord_id)
    today = datetime.now().strftime("%d %B %Y")

    lines = [f"📊 **DAILY INTAKE SITREP — {today}**", ""]

    if not entries:
        lines.append("*No entries logged today. Command telemetry incomplete.*")
        lines.append("Use `!log <food>` to begin reporting.")
    else:
        lines.append("**Logged Entries:**")
        for i, e in enumerate(entries, 1):
            time_str = e["logged_at"][11:16]
            lines.append(
                f"`{i}.` **{e['description']}** — "
                f"{e['calories']:.0f} kcal | P: {e['protein_g']:.0f}g | C: {e['carbs_g']:.0f}g | F: {e['fat_g']:.0f}g "
                f"*(logged {time_str})*"
            )
        lines.append("")
        lines.append("**Totals:**")

        def _fmt(val: float, target: int | None, unit: str = "") -> str:
            base = f"**{val:.0f}{unit}**"
            if target:
                return f"{base} / {target}{unit} *({val / target * 100:.0f}%)*"
            return base

        t = profile or {}
        lines.append(f"🔥 Calories: {_fmt(totals['calories'], t.get('target_calories'), ' kcal')}")
        lines.append(f"🥩 Protein:  {_fmt(totals['protein_g'],  t.get('target_protein_g'), 'g')}")
        lines.append(f"🌾 Carbs:    {_fmt(totals['carbs_g'],    t.get('target_carbs_g'),   'g')}")
        lines.append(f"🫒 Fat:      {_fmt(totals['fat_g'],      t.get('target_fat_g'),     'g')}")

    await message.reply("\n".join(lines))


async def generate_image(prompt: str) -> bytes | None:
    payload = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "medium",
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(connect=10, total=600)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_IMAGES_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                item = (data.get("data") or [{}])[0]
                b64 = item.get("b64_json")
                if b64:
                    return base64.b64decode(b64)
                img_url = item.get("url")
                if not img_url:
                    return None
                async with session.get(img_url) as img_resp:
                    if img_resp.status != 200:
                        return None
                    return await img_resp.read()
    except Exception:
        return None


async def handle_image(message: discord.Message) -> None:
    raw = message.content.strip()[len("!image"):].strip()
    if not raw:
        await message.reply("⚠️ Usage: `!image \"prompt goes here\"`")
        return

    prompt = raw
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        prompt = raw[1:-1].strip()
    if not prompt:
        await message.reply("⚠️ Usage: `!image \"prompt goes here\"`")
        return

    async with message.channel.typing():
        image_bytes = await generate_image(prompt)
    if not image_bytes:
        await message.reply("⚠️ Image generation failed.")
        return

    file_obj = discord.File(io.BytesIO(image_bytes), filename="agent-image.png")
    await message.channel.send(file=file_obj)


async def handle_help(message: discord.Message) -> None:
    lines = [
        "🧠 **METCOM COMMAND INTERFACE — AVAILABLE DIRECTIVES**", "",
        "**Talking to AGENT**",
        "`@AGENT <message>` or `!agent <message>` — Address AGENT directly", "",
        "**Operator Profile**",
        "`!profile` — View your operator profile",
        "`!profile set <fields>` — Create or update your profile",
        "  Fields: `height:<cm>` `weight:<kg>` `goal:<kg>` `calories:<kcal>` `protein:<g>` `carbs:<g>` `fat:<g>`",
        "  Example: `!profile set height:180 weight:85 goal:80 calories:2400 protein:180 carbs:240 fat:80`", "",
        "**Food Logging**",
        "`!log <food description>` — Log a food item (macros estimated automatically)",
        "`!log <description> | <calories> <protein> <carbs> <fat>` — Log with explicit macros",
        "  Example: `!log chicken breast 200g | 220 41 0 5`", "",
        "**Image Generation**",
        "`!image \"prompt goes here\"` — Generate a 1024x1024 medium-quality image with GPT Image 2", "",
        "**Daily Intake**",
        "`!intake` — View today's full intake report with totals vs. targets",
        "`!intake clear` — Wipe today's log", "",
        "*GLORY TO METABOLIC COMMAND* 🫡",
    ]
    await message.reply("\n".join(lines))


def clean_prompt(message: discord.Message) -> str:
    content = message.content.strip()

    if content.startswith("!agent"):
        return content.removeprefix("!agent").strip()

    if client.user:
        content = content.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()

    return content


@client.event
async def on_ready():
    print(f"AGENT online as {client.user}")
    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="metabolic telemetry 🧠",
    ))


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Keyword reactions — fire on all visible messages
    content_lower = message.content.lower()
    for keyword, emoji in KEYWORD_REACTIONS.items():
        if keyword in content_lower:
            await message.add_reaction(emoji)
            break

    # Command routing
    content = message.content.strip()
    if content.startswith("!help"):
        await handle_help(message)
        return
    if content.startswith("!profile"):
        await handle_profile(message)
        return
    if content.startswith("!log"):
        await handle_log(message)
        return
    if content.startswith("!intake"):
        await handle_intake(message)
        return
    if content.startswith("!image"):
        await handle_image(message)
        return

    if not should_respond(message):
        return

    prompt = clean_prompt(message)
    if not prompt:
        prompt = "Issue a brief operational greeting to the Metabolic Command."

    history = list(channel_history[message.channel.id])
    profile_context = format_profile_context(str(message.author.id))

    async with message.channel.typing():
        try:
            reply = await ask_openai(prompt, message.author.display_name, history, profile_context)
        except Exception as e:
            print(f"ask_openai error: {e}")
            await message.reply("🔴 **METCOM SYSTEMS FAILURE** — Inference node unreachable. AGENT is experiencing technical difficulties. Command telemetry offline. Stand by.")
            return

    channel_history[message.channel.id].append({"role": "user", "content": f"Discord user {message.author.display_name} says:\n{prompt}"})
    channel_history[message.channel.id].append({"role": "assistant", "content": reply})

    chunks = split_reply(reply)
    await message.reply(chunks[0])
    for chunk in chunks[1:]:
        await message.channel.send(chunk)

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in environment.")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in environment.")

client.run(DISCORD_TOKEN)