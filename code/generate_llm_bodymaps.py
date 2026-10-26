"""
Ask the three chatbots to produce body maps for feelings, as structured JSON.

Two conditions separate KNOWLEDGE from USE:
  emotion : the feeling is named ("Where in the body do people feel sadness?")
  phrase  : the user's own sentence from the main study is given ("Someone says: 'دلم گرفته'...")
If a model maps sadness to the chest/throat when asked directly, but did not recognise sadness
in the drawings, the problem is in using the knowledge, not in having it.

Body regions are fixed (16), so maps can be compared with the human drawings and with
Nummenmaa et al. (2014, PNAS) "Bodily maps of emotions".

Usage:
  python generate_llm_bodymaps.py --dry-run     # prints the prompts, no API calls
  python generate_llm_bodymaps.py --pilot       # 1 item x 3 models x 1 run
  python generate_llm_bodymaps.py               # everything (9 items x 2 languages x 3 models x 3 runs = 162 calls)

The API key is read from OPENROUTER_API_KEY. Results: llm_bodymaps.csv (one row per call, raw JSON kept).
"""

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, timezone

MODELS = {
    "openai": "openai/gpt-6.1-sol",
    "anthropic": "anthropic/claude-sonnet-5.5",
    "google": "google/gemini-3.8-flash",
}
RUNS = 3
TEMPERATURE = 1.0
MAX_TOKENS = 1500
PAUSE_SECONDS = 1.0
OUTPUT_FILE = "llm_bodymaps.csv"

# key: (English label, Persian label)
REGIONS = {
    "head_top":        ("top of the head / forehead", "بالای سر / پیشانی"),
    "face":            ("face (eyes, cheeks, jaw)", "صورت (چشم، گونه، فک)"),
    "throat":          ("throat / front of the neck", "گلو / جلوی گردن"),
    "neck_shoulders":  ("back of the neck and shoulders", "پشت گردن و شانه‌ها"),
    "chest_upper":     ("upper chest", "بالای قفسه سینه"),
    "heart_area":      ("heart area (left chest)", "ناحیه قلب (سمت چپ سینه)"),
    "sternum_center":  ("centre of the chest / breastbone", "وسط سینه / جناغ"),
    "stomach":         ("stomach / upper abdomen", "معده / بالای شکم"),
    "lower_abdomen":   ("lower abdomen / belly", "پایین شکم / زیر ناف"),
    "upper_back":      ("upper back / between the shoulder blades", "بالای کمر / بین دو کتف"),
    "lower_back":      ("middle and lower back", "وسط و پایین کمر"),
    "arms":            ("arms", "بازوها"),
    "hands":           ("hands", "دست‌ها"),
    "thighs":          ("thighs", "ران‌ها"),
    "lower_legs":      ("lower legs", "ساق پاها"),
    "feet":            ("feet", "پاها (کف و مچ پا)"),
}
LEVELS = ["increase", "decrease", "none"]

# Items. Emotions: the two targets of the study + three anchors with well-known human maps.
ITEMS = [
    {"item": "sadness",   "condition": "emotion", "en": "sadness",   "fa": "غم"},
    {"item": "anxiety",   "condition": "emotion", "en": "anxiety",   "fa": "اضطراب و دلشوره"},
    {"item": "happiness", "condition": "emotion", "en": "happiness", "fa": "شادی"},
    {"item": "fear",      "condition": "emotion", "en": "fear",      "fa": "ترس"},
    {"item": "anger",     "condition": "emotion", "en": "anger",     "fa": "خشم"},
    # Phrases: exactly the user messages of the main study
    {"item": "S1", "condition": "phrase",
     "en": "For a few days I've just felt off. I don't know what's wrong with me.",
     "fa": "چند روزه حس می‌کنم یه جوریم، نمی‌دونم چمه."},
    {"item": "S3", "condition": "phrase",
     "en": "For a few days my heart has felt heavy. I don't know what's wrong with me.",
     "fa": "چند روزه دلم گرفته، نمی‌دونم چمه."},
    {"item": "S4", "condition": "phrase",
     "en": "For a few days I've had a knot in my stomach. I don't know what's wrong with me.",
     "fa": "چند روزه دلشوره دارم و دلم آشوبه، نمی‌دونم چمه."},
    {"item": "S8", "condition": "phrase",
     "en": "For a few days it's been hard for me to take a full breath. I don't know what's wrong with me.",
     "fa": "چند روزه انگار درست نمی‌تونم نفس بکشم، نمی‌دونم چمه."},
]


def region_list(lang):
    i = 0 if lang == "en" else 1
    return "\n".join(f'- "{k}": {v[i]}' for k, v in REGIONS.items())


def json_shape():
    body = ", ".join(f'"{k}": "increase|decrease|none"' for k in REGIONS)
    return '{"regions": {' + body + '}, "feeling": "<the feeling you think it is>"}'


def build_prompt(item, lang):
    text = item[lang]
    if lang == "en":
        if item["condition"] == "emotion":
            q = f"When people feel {text}, in which parts of the body do they usually feel it?"
        else:
            q = f'Someone says to you: "{text}"\nIn which parts of their body is what they feel likely to show up?'
        return (q + "\nFor each region below, answer:\n"
                "  increase = the region feels more active, tense, heavy, warm or strong\n"
                "  decrease = the region feels weaker, empty, numb or less active\n"
                "  none     = the region is not usually involved\n\n"
                + region_list("en") +
                "\n\nAnswer with ONE JSON object and nothing else, in this shape:\n" + json_shape())
    else:
        if item["condition"] == "emotion":
            q = f"وقتی آدم‌ها {text} را تجربه می‌کنند، معمولاً آن را در کدام قسمت‌های بدن حس می‌کنند؟"
        else:
            q = f"کسی به تو می‌گوید: «{text}»\nاحتمالاً چیزی که حس می‌کند در کدام قسمت‌های بدنش ظاهر می‌شود؟"
        return (q + "\nبرای هر ناحیهٔ زیر جواب بده:\n"
                "  increase = آن ناحیه فعال‌تر، سفت‌تر، سنگین‌تر، گرم‌تر یا قوی‌تر حس می‌شود\n"
                "  decrease = آن ناحیه ضعیف‌تر، خالی، بی‌حس یا کم‌فعال‌تر حس می‌شود\n"
                "  none     = آن ناحیه معمولاً درگیر نیست\n\n"
                + region_list("fa") +
                "\n\nفقط و فقط یک شیء JSON با همین کلیدهای انگلیسی برگردان، به این شکل "
                "(مقدار feeling را به فارسی بنویس):\n" + json_shape())


def parse(reply):
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None, "no JSON found"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f"bad JSON: {e}"
    regions = data.get("regions", {})
    out = {}
    for k in REGIONS:
        v = str(regions.get(k, "")).strip().lower()
        out[k] = v if v in LEVELS else "missing"
    return {"regions": out, "feeling": data.get("feeling", "")}, ""


_client = None


def ask(model_id, prompt):
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
    r = _client.chat.completions.create(
        model=model_id, messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        extra_body={"reasoning": {"exclude": True}})
    return r.choices[0].message.content or "", r.model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    args = ap.parse_args()

    jobs = [(p, m, it, lang, run) for p, m in MODELS.items() for it in ITEMS
            for lang in ("en", "fa") for run in range(1, RUNS + 1)]
    if args.pilot:
        jobs = [j for j in jobs if j[2]["item"] == "sadness" and j[3] == "en" and j[4] == 1]
    if args.dry_run:
        for it in (ITEMS[0], ITEMS[6]):
            for lang in ("en", "fa"):
                print("=" * 60, it["item"], lang, "\n" + build_prompt(it, lang))
        print(f"\n{len(jobs)} calls would be made.")
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        print('No OPENROUTER_API_KEY. Set it in your Terminal with: export OPENROUTER_API_KEY="..."')
        return

    fields = ["timestamp_utc", "provider", "model_returned", "item", "condition", "language", "run",
              "feeling", *REGIONS.keys(), "parse_error", "raw"]
    done = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            done = {(r["provider"], r["item"], r["language"], r["run"])
                    for r in csv.DictReader(f) if not r["parse_error"]}
    new = not os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        for n, (prov, model_id, it, lang, run) in enumerate(jobs, 1):
            if (prov, it["item"], lang, str(run)) in done:
                continue
            try:
                reply, returned = ask(model_id, build_prompt(it, lang))
                parsed, err = parse(reply)
            except Exception as e:
                reply, returned, parsed, err = "", "", None, f"{type(e).__name__}: {e}"
                if "402" in str(e):
                    print("Out of credit. Run again later to continue."); return
            row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "provider": prov,
                   "model_returned": returned, "item": it["item"], "condition": it["condition"],
                   "language": lang, "run": run, "parse_error": err, "raw": reply,
                   "feeling": parsed["feeling"] if parsed else ""}
            if parsed:
                row.update(parsed["regions"])
            w.writerow(row); f.flush()
            print(f"[{n}/{len(jobs)}] {prov} {it['item']} {lang} run {run}" + (f"  ERROR {err[:80]}" if err else ""))
            time.sleep(PAUSE_SECONDS)
    print(f"Done. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
