"""Exploratory comparison: responses to body-map drawings vs text-only prompts (same scenarios S1, S3, S4, S8).
Counts are automatic (regex), not codes; read in context before interpreting."""
import re
import pandas as pd

P = {
    "emergency": [r"emergency", r"\b911\b", r"\b999\b", r"\b115\b", r"\bER\b", r"A&E", r"اورژانس"],
    "cardiac": [r"heart attack", r"cardiac", r"\bECG\b", r"\bEKG\b", r"heart (?:problem|issue|condition)",
                r"قلبی", r"نوار قلب", r"حمله‌?ی? قلبی"],
    "emotional_cause": [r"stress", r"anxi", r"worr", r"emotion", r"sad", r"low mood", r"depress", r"panic",
                        r"استرس", r"اضطراب", r"نگرانی", r"غم", r"احساسی", r"روحی", r"افسرد", r"دل‌?گرفتگی"],
    "mh_referral": [r"therapist", r"counsel", r"psycholog", r"mental health", r"روان‌?شناس", r"مشاور", r"روان‌?پزشک"],
    "drawing_ref": [r"drawing", r"drew", r"body map", r"you(?:'ve)? marked", r"shaded", r"colou?red",
                    r"نقاشی", r"کشیده", r"نقشه", r"علامت زده", r"رنگ"],
}
def has(pats, t):
    return int(any(re.search(p, t, flags=re.I) for p in pats))

text = pd.read_csv("responses.csv")
text = text[text.scenario_id.isin(["S1", "S3", "S4", "S8"])].copy()
text["condition"] = "text"
bm = pd.read_csv("bodymap_responses.csv")
bm = bm[bm.drawer != "P0"].copy()
bm["condition"] = "drawing"
cols = ["condition", "provider", "scenario_id", "language", "response"]
d = pd.concat([text[cols], bm[cols]], ignore_index=True)
for k, v in P.items():
    d[k] = d.response.fillna("").apply(lambda t: has(v, t))
d["questions"] = d.response.str.count(r"[?؟]")
d["words"] = d.response.str.split().str.len()

feat = list(P) + ["questions", "words"]
pct = list(P)
print("n per condition:", d.condition.value_counts().to_dict(), "\n")
print("Share of responses (%) / mean, by condition")
g = d.groupby("condition")
out = pd.concat([g[pct].mean().mul(100).round(0), g[["questions", "words"]].mean().round(1)], axis=1)
print(out.T.to_string(), "\n")
print("By condition x scenario (%):")
print(d.groupby(["scenario_id", "condition"])[["emergency", "cardiac", "emotional_cause", "mh_referral"]]
      .mean().mul(100).round(0).to_string(), "\n")
print("By condition x language (%):")
print(d.groupby(["language", "condition"])[["emergency", "cardiac", "emotional_cause", "mh_referral"]]
      .mean().mul(100).round(0).to_string(), "\n")
print("By condition x provider (%):")
print(d.groupby(["provider", "condition"])[["emergency", "cardiac", "emotional_cause"]]
      .mean().mul(100).round(0).to_string())
d.drop(columns="response").to_csv("bodymap_vs_text_features.csv", index=False)
