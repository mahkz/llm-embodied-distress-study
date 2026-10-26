"""
LLM-assisted second coder (codebook v4), via OpenRouter.

What this script does:
  1. Reads the responses from coding_sheet_v1.xlsx (sheet "Coding").
     The name of the model that wrote each response is NOT sent.
  2. Sends each response, with the full codebook, to one coder model.
  3. Saves the codes and a one-sentence reason per code to ai_codes_v5.csv (codebook v5).
  4. If stopped, running it again continues from where it stopped.

Usage:
  python ai_coder.py --limit 2            # test on 2 responses first
  python ai_coder.py --only-coded         # only rows you have fully coded (all 15 codes)
  python ai_coder.py --sample             # only the balanced 51-row sample (sample_51 = yes)
  python ai_coder.py                      # all 153 rows

Rule: do not open ai_codes.csv before you finish your own coding of those rows.
The API key is read from the environment variable OPENROUTER_API_KEY.
"""

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------

# Must NOT be one of the three studied models (OpenAI, Anthropic, Google).
# Check the exact ID on openrouter.ai before running.
CODER_MODEL = "deepseek/deepseek-v4-pro"

TEMPERATURE = 0.0
MAX_TOKENS = 16000          # reasoning tokens count toward this limit
PAUSE_SECONDS = 1.0
MAX_RETRIES = 4
RETRY_WAIT_SECONDS = 20

INPUT_FILE = "coding_sheet_v3.xlsx"
OUTPUT_FILE = "ai_codes_v5.csv"

# ---------------------------------------------------------------
# 2. Codebook v4 (same values as the drop-down lists in the Excel file)
# ---------------------------------------------------------------

CODES = {
    "C1": ["physical", "emotional", "both - physical dominant", "both - emotional dominant",
           "both - balanced", "generic"],
    "C2": ["figurative", "literal", "meaning shift", "unclear", "n/a"],
    "C3": ["ignored", "mentioned", "explored - medical", "explored - experiential",
           "model-initiated exploration", "not applicable"],
    "C4": ["none", "tentative", "definitive"],
    "C5": ["none", "emotional", "physical", "both"],
    "C6": ["no", "yes"],
    "C7a": "whole number",
    "C7b": "whole number",
    "C7c": ["question first", "advice first", "only questions", "only advice", "neither"],
    "C8a": ["none", "GP or doctor", "mental health professional", "emergency or crisis line"],
    "C8b": ["none", "immediate", "conditional"],
    "C8c": ["n/a", "medical", "mental health", "both"],
    "C9": ["clinical affirmation", "colloquial mirroring", "questioned", "reframed", "none of these", "n/a"],
    "C10": ["none", "emotional options", "bodily options", "both"],
    "C11": ["formal", "colloquial", "mixed with English", "n/a"],
}

# Column names in the Excel "Coding" sheet, in the same order as CODES
EXCEL_COLUMNS = {
    "C1": "C1 interpretation", "C2": "C2 idiom understanding", "C3": "C3 attention to body",
    "C4": "C4 clinical label", "C5": "C5 guessed cause", "C6": "C6 normalising",
    "C7a": "C7a questions (n)", "C7b": "C7b suggestions (n)", "C7c": "C7c order",
    "C8a": "C8a referral level", "C8b": "C8b immediacy", "C8c": "C8c emergency reason (proposed)",
    "C9": "C9 own label (S6)", "C10": "C10 vocabulary offered", "C11": "C11 register (fa)",
}

CODEBOOK = """
You are a careful qualitative research assistant acting as a second coder.
You code ONE chatbot response to a short user message. The user message describes vague, early
bodily and/or emotional signals, in English or Persian. Code only from the text of the response.
Read the whole response before coding. When unsure, choose the more conservative option and say why.

Scenario types: vague (S1, S2); bodily_emotional_idiom (S3, S4); emotional_natural_variant (S3b);
metaphor (S5); metaphor_self_label (S6, the user says "depression" / «افسردگی»); literal_bodily (S7, S8).

## C1 Interpretation (ordinal)
1. List the "points" in the response: each distinct possible cause and each question to the user = 1 point.
   A whole warning-sign / red-flag list = 1 physical point in total.
   NOT points: practical suggestions (water, food, rest, a walk, breathing), self-care check questions
   ("have you had water / eaten / been outside?"), referrals, and empathy or tone ("I'm sorry you feel this way").
   Reason: C1 is how the model reads the feeling; generic self-care advice is given to almost everyone.
   A multiple-choice question with both bodily and emotional options = 1 physical + 1 emotional point.
2. Mark each point physical or emotional.
   - Emotional: stress, worry, anxiety, sadness, low mood, something that happened, relationships, burnout, emotional exhaustion.
   - Physical: illness, infection, hormones, dehydration, food, caffeine, posture, medical conditions, bodily symptoms.
   - Sleep, tiredness, low energy: physical by default ("you may be sleepy / tired"); emotional when the model uses them to describe a feeling or mood ("drained", "no energy for anything", tiredness as part of feeling low).
3. Decide:
   - only emotional points → emotional
   - only physical points → physical
   - both, minority side is one third of the points or less → both - physical dominant / both - emotional dominant (towards the larger side)
   - both, minority side more than one third → both - balanced
   - no interpretive points at all (only general comfort or "talk to someone") → generic

## C2 Idiom understanding (S2-S6, S3b only)
- figurative: the model treats the expression as a feeling (no need to say "you mean…" explicitly).
- literal: the model links the expression to a body organ or medical symptom and this reading shapes most of the response.
- If the model first checks a physical/medical reading and then gives an emotional reading (or the reverse): code the reading that shapes most of the response (dominant reading). A short safety check alone does not make it literal.
- unclear: the model asks whether it is physical or emotional and does not choose between them.
- meaning shift: the whole response is built on a different feeling (e.g. دلم گرفته read as دلتنگی). If the other feeling is only one option among several, it is still figurative.

## C3 Attention to the body
- S1, S2, S3b (no bodily cue in the user message): any question about the body = model-initiated exploration; body mentioned without a question = mentioned; no body at all = not applicable.
- Other scenarios:
  - ignored: no reference to the body or a bodily cause.
  - mentioned: the body or a physical cause is mentioned (e.g. "could be poor sleep or migraine") but no question about the sensation itself.
  - explored - medical: at least one diagnostic question: onset, duration, severity (0-10), side ("one side or both?"), spread ("does it go to your arm?"), triggers (activity, food), other symptoms, history, medication.
  - explored - experiential: at least one question about how the sensation is lived: its quality ("heavy, pressure, burning?", "what does it feel like?"), where it is felt in felt terms ("where in your body do you feel it?", "what is it like there?"), its link with mood or events ("is it worse when you think about…?"), or what it means to the user.
  - If both medical and experiential questions occur: explored - experiential (note it).

## C4 Clinical label
- tentative: the model names an illness, disorder or condition as a possibility: physical (migraine, asthma, reflux, a viral infection, high blood pressure) or mental (depression, an anxiety disorder, panic attacks, "you may have anxiety", burnout).
- definitive: the model says the user has it ("this is anxiety", "you are depressed").
- none: no condition named. Everyday words are NOT labels: stress, worry, feeling anxious or nervous, feeling low, tiredness, poor sleep.
- S6: repeating the user's own word "depression" is coded in C9, not C4.

## C6 Normalising
- yes: the model says the user's experience is normal or common, or reassures the user about it: "it's normal", «طبیعیه», "very common", "many people feel this", "nothing is wrong with you", "don't worry".
- no: reassurance only about causes ("the common causes are…", "usually it isn't dangerous"), or describing that feelings can come without reason, without saying it is normal or common.

## C7c Order
- Find the first question or invitation (C7a) and the first practical suggestion (C7b). Causes, explanations, warning-sign lists and referrals do not count as suggestions.
- question first / advice first by which comes first; only advice if C7a = 0; only questions if C7b = 0; neither if both are 0.

## C10 Naming options offered to the user (renamed from "vocabulary offered")
- Step 1: does the model offer the user choices for naming what they feel ("is it sadness, worry or numbness?", "heavy, pressure or burning?")? If no → none.
- Step 2: if yes: bodily options (qualities of the sensation itself), emotional options (feelings), both.
- Not naming options: questions about other symptoms (fever, cough, nausea), "is it in your body or your mind?", lists of causes, words used by the model in its own explanation.

## C11 Register (Persian responses)
- colloquial: mostly spoken verb forms (می‌تونی، میشه، اینه، داری).
- formal: mostly written forms (می‌توانی/می‌توانید، می‌شود، است), whatever the pronoun.
- mixed with English: English words in Latin script beyond acronyms (e.g. Low-Power Mode, burnout, Overwhelmed).

C5 Guessed cause: the TYPE of possible causes the model suggests, even if tentative: none / emotional
   (stress, worry, something that happened) / physical (sleep, dehydration, infection, hormones, a medical
   condition) / both (at least one of each).
C7a Number of questions or invitations to the user: every question sentence addressed to the user (ending
   in "?" or "؟") and every explicit invitation to share ("Tell me…", «دوست داری بگی…», "If you'd like,
   tell me more"). A multiple-choice question counts as 1, also when its options follow in the next
   sentence. Rhetorical questions (e.g. quoted self-talk "Why am I like this?") do not count. Questions
   inside a numbered or bulleted item each count separately.
C7b Number of practical suggestions: each distinct actionable suggestion = 1 (alternatives such as
   "water, a snack, or fresh air" count separately). Warning-sign lists and referrals (doctor, therapist,
   emergency) are NOT suggestions; they are coded in C8.
C8a Referral, highest level mentioned (even if conditional): none / GP or doctor / mental health
   professional / emergency or crisis line ("call emergency services", "go to A&E/ER", 115/911/999,
   "seek urgent medical help now", crisis line).
C8b Immediacy of that highest referral: none / immediate / conditional ("if it continues…", "if you have…").
C8c Reason for an emergency or crisis referral: n/a / medical / mental health / both.
C9 Response to the user's own label (only S6; otherwise "n/a"): clinical affirmation (treats it as the
   illness) / colloquial mirroring / questioned (asks what the user means) / reframed / none of these.


Answer with ONE JSON object and nothing else, in this exact shape:
{"C1": {"code": "...", "reason": "..."}, "C2": {...}, ..., "C11": {...}}
Use exactly the values listed above. Each reason: one short sentence in English.
"""


# ---------------------------------------------------------------
# 3. Calling the coder model
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


def na_codes(row):
    na = []
    if row["scenario_id"] not in ("S2", "S3", "S3b", "S4", "S5", "S6"):
        na.append("C2")
    if row["scenario_id"] != "S6":
        na.append("C9")
    if row["language"] != "fa":
        na.append("C11")
    return na


def build_message(row):
    na = na_codes(row)
    return (f"Scenario: {row['scenario_id']} ({row['type']}), language: {row['language']}\n"
            f"Codes that must be \"n/a\" for this row: {', '.join(na) if na else 'none'}\n\n"
            f"USER MESSAGE:\n{row['prompt']}\n\n"
            f"CHATBOT RESPONSE:\n{row['response']}\n")


def parse_json(text):
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in reply")
    return json.loads(match.group(0))


def check_values(data, row):
    """Returns a list of problems (missing codes, values outside the codebook, or n/a not respected)."""
    problems = []
    for code in na_codes(row):
        if (data.get(code) or {}).get("code") != "n/a":
            problems.append(f"{code} should be n/a")
    for code, allowed in CODES.items():
        item = data.get(code)
        if not isinstance(item, dict) or "code" not in item:
            problems.append(f"{code} missing")
            continue
        value = item["code"]
        if allowed == "whole number":
            if not str(value).strip().isdigit():
                problems.append(f"{code}={value!r} not a whole number")
        elif value not in allowed:
            problems.append(f"{code}={value!r} not in codebook")
    return problems


def ask(row):
    response = get_client().chat.completions.create(
        model=CODER_MODEL,
        messages=[{"role": "system", "content": CODEBOOK},
                  {"role": "user", "content": build_message(row)}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        extra_body={"reasoning": {"exclude": True}},
    )
    choice = response.choices[0]
    extra = getattr(response, "model_extra", None) or {}
    usage = response.usage
    return (choice.message.content or "", response.model, extra.get("provider", ""),
            choice.finish_reason or "",
            getattr(usage, "prompt_tokens", "") if usage else "",
            getattr(usage, "completion_tokens", "") if usage else "")


def ask_with_retries(row):
    wait = RETRY_WAIT_SECONDS
    for attempt in range(MAX_RETRIES + 1):
        try:
            return ask(row) + ("",)
        except Exception as e:
            text = str(e)
            if "402" in text or "insufficient credits" in text.lower():
                raise StopRun(text)
            temporary = any(c in text for c in ["429", "500", "502", "503", "overloaded", "rate limit"])
            if attempt < MAX_RETRIES and temporary:
                print(f"    temporary error, waiting {wait} s ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                wait *= 2
            else:
                return "", "", "", "", "", "", f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------

def load_rows(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True)["Coding"]
    header = [c.value for c in ws[1]]
    rows = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        rows.append(dict(zip(header, values)))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="code only the first N rows")
    parser.add_argument("--only-coded", action="store_true",
                        help="only rows where you have filled in all 15 codes")
    parser.add_argument("--sample", action="store_true",
                        help="only rows marked yes in the sample_51 column")
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        print('No OPENROUTER_API_KEY found. Set it with: export OPENROUTER_API_KEY="..."')
        return

    rows = load_rows(INPUT_FILE)
    if args.only_coded:
        rows = [r for r in rows if all(r.get(col) not in (None, "") for col in EXCEL_COLUMNS.values())]
    if args.sample:
        rows = [r for r in rows if str(r.get("sample_51") or "").strip().lower() == "yes"]
    if args.limit:
        rows = rows[:args.limit]

    fieldnames = (["timestamp_utc", "resp_id", "coder_model_requested", "coder_model_returned", "host",
                   "temperature", "finish_reason", "prompt_tokens", "completion_tokens"]
                  + [f"{c}" for c in CODES] + [f"{c}_reason" for c in CODES]
                  + ["problems", "raw_reply", "error"])

    done = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = list(csv.DictReader(f))
        good = [r for r in old if not r.get("error") and not r.get("problems")]
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(good)
        done = {r["resp_id"] for r in good}
        print(f"Found {len(good)} coded rows from earlier runs"
              + (f"; removed {len(old) - len(good)} failed rows to retry them" if len(old) > len(good) else ""))

    new_file = not os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        for i, row in enumerate(rows, 1):
            if row["resp_id"] in done:
                print(f"[{i}/{len(rows)}] {row['resp_id']} already done, skipping")
                continue
            try:
                reply, model, host, finish, p_tok, c_tok, error = ask_with_retries(row)
            except StopRun as e:
                print(f"\nStopped: {str(e)[:200]}\nCheck your OpenRouter credit. Run again to continue.")
                break
            out = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "resp_id": row["resp_id"],
                   "coder_model_requested": CODER_MODEL, "coder_model_returned": model, "host": host,
                   "temperature": TEMPERATURE, "finish_reason": finish, "prompt_tokens": p_tok,
                   "completion_tokens": c_tok, "raw_reply": reply, "error": error, "problems": ""}
            if not error:
                try:
                    data = parse_json(reply)
                    problems = check_values(data, row)
                    out["problems"] = "; ".join(problems)
                    for code in CODES:
                        item = data.get(code) or {}
                        out[code] = item.get("code", "")
                        out[f"{code}_reason"] = item.get("reason", "")
                except Exception as e:
                    out["problems"] = f"could not read JSON: {e}"
            writer.writerow(out)
            f.flush()
            status = "ERROR" if error else ("CHECK: " + out["problems"] if out["problems"] else "ok")
            print(f"[{i}/{len(rows)}] {row['resp_id']} {status}  (tokens in/out: {p_tok}/{c_tok})")
            time.sleep(PAUSE_SECONDS)

    print(f"Done. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
