"""Agreement between the reference codes and the second coder (DeepSeek) on the
49 responses both coders covered (rows with a referral code from both).
Reproduces the kappa values reported in Section 3.3 of the report.
Run from the repository root: python code/reliability.py"""
import pandas as pd, numpy as np
from sklearn.metrics import cohen_kappa_score

H = pd.read_csv("coding/reference_codes.csv", dtype=str).fillna("").set_index("resp_id")
A = pd.read_csv("coding/second_coder_deepseek_codes.csv", dtype=str).fillna("").set_index("resp_id")
COLS = {"C1": "C1 interpretation", "C2": "C2 idiom understanding", "C3": "C3 attention to body",
        "C4": "C4 clinical label", "C6": "C6 normalising", "C7c": "C7c order",
        "C8a": "C8a referral level", "C10": "C10 vocabulary offered"}
ORD = {"physical": 0, "both - physical dominant": 1, "both - balanced": 2,
       "both - emotional dominant": 3, "emotional": 4}

def norm(x, code):
    x = x.strip().lower().replace(" options", "")
    return x.split(" - ")[0] if code == "C4" else x

ids = [r for r in H.index if r in A.index and H.loc[r, COLS["C8a"]].strip() and A.loc[r, "C8a"].strip()]
print(f"overlap: {len(ids)} responses")
for code, col in COLS.items():
    pairs = [(norm(H.loc[r, col], code), norm(A.loc[r, code], code)) for r in ids]
    pairs = [(a, b) for a, b in pairs if a and b]
    if code == "C1":
        pairs = [(ORD[a], ORD[b]) for a, b in pairs if a in ORD and b in ORD]
        x, y = zip(*pairs)
        k = cohen_kappa_score(x, y, weights="linear")
        within = np.mean([abs(a - b) <= 1 for a, b in pairs])
        print(f"{code}: n={len(pairs)}  weighted kappa={k:.2f}  within one step={within:.0%}")
    else:
        x, y = zip(*pairs)
        print(f"{code}: n={len(pairs)}  kappa={cohen_kappa_score(x, y):.2f}")
