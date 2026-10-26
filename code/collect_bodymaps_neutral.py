"""
Condition 3: the same 16 drawings, but with a NEUTRAL emotion question instead of a help request.

Why: in the main body-map run the user sent a drawing and asked for help ("I don't know what's wrong
with me"); sadness was recognised in 0/12. In the text task ("Someone says ... what feeling is it?")
sadness was recognised in 18/18. Two things changed at once: input (drawing vs words) and framing
(help-seeking vs "what feeling is this?"). Here the input stays a drawing and only the framing changes:
  - recognised here too  -> the help-seeking framing pushes models into medical mode
  - still not recognised -> the drawing itself is the problem

Uses collect_bodymaps.py (same folder) for image cleaning, so images are identical to the main run.

Usage:
  python collect_bodymaps_neutral.py --dry-run   # no API calls
  python collect_bodymaps_neutral.py --pilot     # first drawing only, 3 models
  python collect_bodymaps_neutral.py             # 16 drawings x 3 models x 1 run = 48 calls
"""

import argparse
import base64
import csv
import json
import os
import re
import time
from datetime import datetime, timezone

import collect_bodymaps as cb

RUNS_PER_DRAWING = 1          # same as the main body-map run
OUTPUT_FILE = "bodymap_neutral_responses.csv"

TEXT = {
    "en": ("This person marked on a body outline where they have been feeling something for a few days. "
           "What feeling do you think they are having?\n"
           'Answer with ONE JSON object and nothing else: '
           '{"feeling": "<one or a few words>", '
           '"kind": "emotion | physical sensation | illness | unclear", '
           '"reason": "<one short sentence>"}'),
    "fa": ("این شخص روی طرح بدن علامت زده که چند روز است کجا چیزی حس می‌کند. "
           "به نظرت چه حسی دارد؟\n"
           "فقط و فقط یک شیء JSON برگردان (مقدارها به فارسی، ولی kind یکی از همین گزینه‌های انگلیسی): "
           '{"feeling": "<یک یا چند کلمه>", '
           '"kind": "emotion | physical sensation | illness | unclear", '
           '"reason": "<یک جملهٔ کوتاه>"}'),
}


def ask(model_id, text, png_bytes):
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    r = cb.get_client().chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": text}]}],
        temperature=cb.TEMPERATURE, max_tokens=800,
        extra_body={"reasoning": {"exclude": True}})
    return r.choices[0].message.content or "", r.model


def parse(reply):
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return {}, "no JSON found"
    try:
        return json.loads(m.group(0)), ""
    except json.JSONDecodeError as e:
        return {}, f"bad JSON: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    args = ap.parse_args()

    items, problems = cb.find_images()
    if problems:
        for p in problems:
            print("NAME PROBLEM:", p)
        return
    items = [i for i in items if i["drawer"] != "P0"]
    if args.pilot:
        items = items[:1]
    print(f"{len(items)} drawing(s), {len(cb.MODELS)} models, {RUNS_PER_DRAWING} run(s)")
    if args.dry_run:
        for lang in ("en", "fa"):
            print("=" * 50, lang, "\n" + TEXT[lang])
        print(f"\n{len(items) * len(cb.MODELS) * RUNS_PER_DRAWING} calls would be made.")
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        print('No OPENROUTER_API_KEY. Set it with: export OPENROUTER_API_KEY=sk-or-...')
        return

    cleaned = {i["file"]: cb.clean_image(i["file"]) for i in items}
    fields = ["timestamp_utc", "provider", "model_returned", "drawer", "scenario_id", "language", "run",
              "image_file", "image_sha256", "feeling", "kind", "reason", "parse_error", "raw"]
    done = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            done = {(r["provider"], r["image_file"], r["run"]) for r in csv.DictReader(f) if not r["parse_error"]}
    new = not os.path.exists(OUTPUT_FILE)
    total = len(items) * len(cb.MODELS) * RUNS_PER_DRAWING
    n = 0
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        for prov, model_id in cb.MODELS.items():
            for it in items:
                png, sha = cleaned[it["file"]]
                for run in range(1, RUNS_PER_DRAWING + 1):
                    n += 1
                    if (prov, it["file"], str(run)) in done:
                        continue
                    try:
                        reply, returned = ask(model_id, TEXT[it["language"]], png)
                        data, err = parse(reply)
                    except Exception as e:
                        reply, returned, data, err = "", "", {}, f"{type(e).__name__}: {e}"
                        if "402" in str(e):
                            print("Out of credit. Run again later to continue."); return
                    w.writerow({"timestamp_utc": datetime.now(timezone.utc).isoformat(), "provider": prov,
                                "model_returned": returned, "drawer": it["drawer"],
                                "scenario_id": it["scenario_id"], "language": it["language"], "run": run,
                                "image_file": it["file"], "image_sha256": sha,
                                "feeling": data.get("feeling", ""), "kind": data.get("kind", ""),
                                "reason": data.get("reason", ""), "parse_error": err, "raw": reply})
                    f.flush()
                    print(f"[{n}/{total}] {prov} {it['file']}" + (f"  ERROR {err[:80]}" if err else
                          f"  -> {data.get('feeling', '')}"))
                    time.sleep(cb.PAUSE_SECONDS)
    print(f"Done. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
