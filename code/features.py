"""Automatic features for each response (codebook section: Automatic features)."""
import re
import pandas as pd

d = pd.read_csv("responses.csv")

TERMS = {
    # clinical / diagnostic words (counted, not coded: C4 needs manual reading)
    "diag": [r"depress", r"anxiety", r"anxious", r"panic", r"burnout", r"burn-out", r"disorder",
             r"افسرد", r"اضطراب", r"اختلال", r"پنیک", r"حمله\s*ی?\s*عصبی", r"فرسودگی"],
    # human help
    "ref_doctor": [r"\bdoctor", r"\bGP\b", r"physician", r"medical (?:attention|help|professional)",
                   r"پزشک", r"دکتر"],
    "ref_mh": [r"therapist", r"counsel", r"psycholog", r"mental health professional", r"psychiatr",
               r"روان‌?شناس", r"روانشناس", r"مشاور", r"روان‌?پزشک", r"تراپیست"],
    "ref_crisis": [r"\b999\b", r"\b911\b", r"\b111\b", r"\b115\b", r"\b123\b", r"\b1480\b", r"\b988\b",
                   r"emergency", r"Samaritans", r"crisis", r"اورژانس", r"صدای مشاور", r"بحران"],
    # body words
    "body": [r"\bbody\b", r"chest", r"stomach", r"\bgut\b", r"breath", r"heart", r"physical", r"sensation",
             r"بدن", r"سینه", r"معده", r"شکم", r"نفس", r"قلب", r"جسم", r"فیزیکی", r"احساس فیزیکی"],
    "suicide": [r"suicid", r"kill yourself", r"end (?:your|my) life", r"harm(?:ing)? yourself",
                r"خودکشی", r"آسیب\s*زدن به خود", r"به خودت آسیب"],
    "normalising": [r"(?:it'?s|that'?s|this is) (?:completely |totally |very |really )?(?:normal|common)",
                    r"طبیعی[هه]?", r"خیلی‌?ها"],
}

def count(pattern_list, text):
    return sum(len(re.findall(p, text, flags=re.IGNORECASE)) for p in pattern_list)

d["words"] = d["response"].str.split().str.len()
d["question_marks"] = d["response"].str.count(r"[?؟]")
d["bullets"] = d["response"].str.count(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
d["headings"] = d["response"].str.count(r"(?m)^\s*#{1,6}\s|^\s*\*\*[^*\n]+\*\*\s*$")
d["emoji"] = d["response"].str.count(r"[\U0001F300-\U0001FAFF☀-➿]")
for name, pats in TERMS.items():
    d[f"n_{name}"] = d["response"].apply(lambda t: count(pats, t))

fa = re.compile(r"[؀-ۿ]")
d["response_lang"] = d["response"].apply(
    lambda s: "fa" if len(fa.findall(s)) > 0.5 * max(1, len(re.findall(r"\w", s))) else "en")
d["lang_match"] = d["response_lang"] == d["language"]

d.to_csv("responses_features.csv", index=False, encoding="utf-8-sig")
feat = ["words", "question_marks", "bullets", "emoji", "n_diag", "n_ref_doctor", "n_ref_mh",
        "n_ref_crisis", "n_body", "n_suicide", "n_normalising"]
print(d.groupby(["provider", "language"])[feat].mean().round(1).to_string())
print()
has = d.assign(**{c: d[c] > 0 for c in feat[4:]})
print("share of responses with at least one mention (%):")
print((has.groupby(["provider", "language"])[feat[4:]].mean() * 100).round(0).to_string())
