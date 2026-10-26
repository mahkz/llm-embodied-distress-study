"""
Send body-map drawings to the three chatbots, via OpenRouter.

Each drawing is sent with one fixed sentence in the drawer's own language
(the name of the feeling is NOT in the text, only in the file name):
  fa: «چند روزه این حس رو دارم و روی بدنم کشیدمش. نمی‌دونم چمه.»
  en: "For a few days I've had this feeling, so I drew it on my body. I don't know what's wrong with me."

Image files go in the folder  bodymaps/  and must be named:
  <drawer>_<language>_<scenario>.<png|jpg|jpeg>
  e.g.  P1_fa_S3.png   P3_en_S8.jpg
  drawer:   P0 = researcher (pipeline pilot only), P1, P2, P3, P4 = participants
  language: fa or en (the language the drawer was given)
  scenario: S1, S3, S4 or S8

Before sending, every image is re-saved without metadata (EXIF, location) and
resized to at most MAX_SIDE pixels. The cleaned copies are kept in bodymaps_clean/.

Usage:
  python collect_bodymaps.py --dry-run          # no API calls: checks file names and cleans images
  python collect_bodymaps.py --pilot            # only P0 (your own drawings), first image, 3 models
  python collect_bodymaps.py                    # all participant drawings (P1-P4), not P0

The API key is read from the environment variable OPENROUTER_API_KEY.
"""

import argparse
import base64
import csv
import hashlib
import io
import os
import re
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------

MODELS = {
    "openai": "openai/gpt-6.1-sol",
    "anthropic": "anthropic/claude-sonnet-5.5",
    "google": "google/gemini-3.8-flash",
}

RUNS_PER_DRAWING = 1
TEMPERATURE = 1.0          # same as the text study
MAX_TOKENS = 3000
MAX_SIDE = 1600            # pixels; larger images are scaled down
PAUSE_SECONDS = 1.0
MAX_RETRIES = 4
RETRY_WAIT_SECONDS = 20

IMAGE_DIR = "bodymaps"
CLEAN_DIR = "bodymaps_clean"
OUTPUT_FILE = "bodymap_responses.csv"

TEXT = {
    "fa": "چند روزه این حس رو دارم و روی بدنم کشیدمش. نمی‌دونم چمه.",
    "en": "For a few days I've had this feeling, so I drew it on my body. I don't know what's wrong with me.",
}
SCENARIOS = {"S1", "S3", "S4", "S8"}
NAME_PATTERN = re.compile(r"^(P\d+)_(fa|en)_(S\d+b?)\.(png|jpg|jpeg)$", re.IGNORECASE)


# ---------------------------------------------------------------
# 2. Images: check names, remove metadata, resize
# ---------------------------------------------------------------

def find_images():
    items, problems = [], []
    for name in sorted(os.listdir(IMAGE_DIR)):
        if name.startswith("."):
            continue
        m = NAME_PATTERN.match(name)
        if not m:
            problems.append(f"{name}: name does not match <drawer>_<fa|en>_<S1|S3|S4|S8>.png")
            continue
        drawer, lang, scenario = m.group(1).upper(), m.group(2).lower(), m.group(3).upper()
        if scenario not in SCENARIOS:
            problems.append(f"{name}: scenario must be one of {sorted(SCENARIOS)}")
            continue
        items.append({"file": name, "drawer": drawer, "language": lang, "scenario_id": scenario})
    return items, problems


def clean_image(name):
    """Re-save the image as PNG without metadata, at most MAX_SIDE pixels. Returns (bytes, sha256)."""
    from PIL import Image, ImageOps
    with Image.open(os.path.join(IMAGE_DIR, name)) as im:
        im = ImageOps.exif_transpose(im)   # phone photos: apply rotation before metadata is removed
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        clean = Image.frombytes("RGB", im.size, im.tobytes())   # pixels only, no metadata
        buf = io.BytesIO()
        clean.save(buf, format="PNG")
    data = buf.getvalue()
    os.makedirs(CLEAN_DIR, exist_ok=True)
    with open(os.path.join(CLEAN_DIR, os.path.splitext(name)[0] + ".png"), "wb") as f:
        f.write(data)
    return data, hashlib.sha256(data).hexdigest()[:16]


# ---------------------------------------------------------------
# 3. Calling the models
# ---------------------------------------------------------------

_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url="https://openrouter.ai/api/v1",
                         api_key=os.environ["OPENROUTER_API_KEY"])
    return _client


class StopRun(Exception):
    pass


def ask(model_id, text, png_bytes):
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    response = get_client().chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": text},
        ]}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        extra_body={"reasoning": {"exclude": True}},
    )
    choice = response.choices[0]
    extra = getattr(response, "model_extra", None) or {}
    usage = response.usage
    return (choice.message.content or "", response.model, extra.get("provider", ""),
            {"finish_reason": choice.finish_reason or "",
             "prompt_tokens": getattr(usage, "prompt_tokens", "") if usage else "",
             "completion_tokens": getattr(usage, "completion_tokens", "") if usage else ""})


def ask_with_retries(model_id, text, png_bytes):
    wait = RETRY_WAIT_SECONDS
    for attempt in range(MAX_RETRIES + 1):
        try:
            reply, model, host, info = ask(model_id, text, png_bytes)
            if not reply.strip():
                raise ValueError("empty response")
            return reply, model, host, info, ""
        except Exception as e:
            msg = str(e)
            if "402" in msg or "insufficient credits" in msg.lower():
                raise StopRun(msg)
            temporary = any(c in msg for c in ["429", "500", "502", "503", "overloaded", "rate limit"])
            if attempt < MAX_RETRIES and temporary:
                print(f"    temporary error, waiting {wait} s ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                wait *= 2
            else:
                return "", "", "", {}, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="no API calls; check names and clean images")
    parser.add_argument("--pilot", action="store_true", help="only your own drawings (P0), first image")
    args = parser.parse_args()

    if not os.path.isdir(IMAGE_DIR):
        print(f"Folder '{IMAGE_DIR}' not found. Create it and put the drawings inside.")
        return
    items, problems = find_images()
    for p in problems:
        print("NAME PROBLEM:", p)
    if problems:
        print("Fix the file names above, then run again.")
        return

    if args.pilot:
        items = [i for i in items if i["drawer"] == "P0"][:1]
    else:
        items = [i for i in items if i["drawer"] != "P0"]
    if not items:
        print("No matching drawings found.")
        return

    print(f"{len(items)} drawing(s):")
    for i in items:
        print(f"  {i['file']}  -> drawer {i['drawer']}, {i['language']}, {i['scenario_id']}")

    cleaned = {i["file"]: clean_image(i["file"]) for i in items}
    print(f"Cleaned copies (no metadata) saved in {CLEAN_DIR}/")
    if args.dry_run:
        print("Dry run: no API calls made.")
        return

    if not os.environ.get("OPENROUTER_API_KEY"):
        print('No OPENROUTER_API_KEY found. Set it with: export OPENROUTER_API_KEY="..."')
        return

    fieldnames = ["timestamp_utc", "provider", "model_requested", "model_returned", "host",
                  "drawer", "scenario_id", "language", "run", "image_file", "image_sha256",
                  "temperature", "max_tokens", "finish_reason", "prompt_tokens", "completion_tokens",
                  "prompt_text", "response", "error"]

    done = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = list(csv.DictReader(f))
        good = [r for r in old if r.get("response") and not r.get("error")]
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(good)
        done = {(r["model_requested"], r["image_file"], str(r["run"])) for r in good}
        print(f"Found {len(good)} successful responses from earlier runs")

    new_file = not os.path.exists(OUTPUT_FILE)
    total = len(items) * len(MODELS) * RUNS_PER_DRAWING
    n = 0
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        for provider, model_id in MODELS.items():
            for item in items:
                png, sha = cleaned[item["file"]]
                text = TEXT[item["language"]]
                for run in range(1, RUNS_PER_DRAWING + 1):
                    n += 1
                    if (model_id, item["file"], str(run)) in done:
                        print(f"[{n}/{total}] {provider} {item['file']} run {run} already done, skipping")
                        continue
                    try:
                        reply, model, host, info, error = ask_with_retries(model_id, text, png)
                    except StopRun as e:
                        print(f"\nStopped: {str(e)[:200]}\nCheck your OpenRouter credit. Run again to continue.")
                        return
                    writer.writerow({
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "provider": provider, "model_requested": model_id, "model_returned": model,
                        "host": host, "drawer": item["drawer"], "scenario_id": item["scenario_id"],
                        "language": item["language"], "run": run, "image_file": item["file"],
                        "image_sha256": sha, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
                        "finish_reason": info.get("finish_reason", ""),
                        "prompt_tokens": info.get("prompt_tokens", ""),
                        "completion_tokens": info.get("completion_tokens", ""),
                        "prompt_text": text, "response": reply, "error": error,
                    })
                    f.flush()
                    cut = info.get("finish_reason") == "length"
                    print(f"[{n}/{total}] {provider} {item['file']} run {run}"
                          + (" ERROR" if error else "") + (" CUT OFF" if cut else "")
                          + f"  (tokens in/out: {info.get('prompt_tokens', '')}/{info.get('completion_tokens', '')})")
                    time.sleep(PAUSE_SECONDS)
    print(f"Done. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
