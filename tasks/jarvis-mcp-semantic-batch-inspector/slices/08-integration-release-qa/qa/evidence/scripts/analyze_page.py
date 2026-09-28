import json, sys
raw = json.loads(json.loads(open("page-raw.json", encoding="utf-8").read()))
S = raw["samples"]; turns = [json.loads(l) for l in open("turns.jsonl", encoding="utf-8")]
print("samples", len(S), "span s", round((S[-1]["t"] - S[0]["t"]) / 1000, 1), "page scene commands sent:", len(raw["reqs"]), "console warn/error:", raw["logs"])
revs = []
for s in S:
    if not revs or revs[-1] != s["rev"]: revs.append(s["rev"])
print("revision sequence seen by the page:", revs)
def ids(s): return {n[0] for n in s["nodes"]}
def off(n, vw, vh): return n[1] < 0 or n[2] < 0 or n[1] + n[3] > vw or n[2] + n[4] > vh
for k, t in enumerate(turns):
    t0, t1 = t["t0"] * 1000, t["t1"] * 1000
    nxt = turns[k + 1]["t0"] * 1000 if k + 1 < len(turns) else S[-1]["t"] + 1
    before = [s for s in S if s["t"] < t0][-1]
    win = [s for s in S if t0 <= s["t"] <= t1]
    sets = []
    for s in win:
        i = frozenset(ids(s))
        if not sets or sets[-1] != i: sets.append(i)
    after = [s for s in S if t1 <= s["t"] < nxt]
    offc = {}
    for s in after:
        for n in s["nodes"]:
            if off(n, s["vw"], s["vh"]):
                c = offc.setdefault(n[0], [0, 0, [9e9, 9e9, -9e9, -9e9]]); c[0] += 1
                c[2] = [min(c[2][0], n[1]), min(c[2][1], n[2]), max(c[2][2], n[1] + n[3]), max(c[2][3], n[2] + n[4])]
    orbit = {}
    for s in after:
        for n in s["nodes"]:
            if n[0].startswith("orion"): orbit.setdefault(n[0], set()).add(n[5])
    xs = {}
    for s in after:
        for n in s["nodes"]:
            if n[0].startswith("orion"):
                a = xs.setdefault(n[0], [9e9, -9e9]); a[0] = min(a[0], n[1]); a[1] = max(a[1], n[1] + n[3])
    print(f"\nT{t['turn']} {t['text']} rev {t['rev_before']}->{t['rev_after']} rendered-set changes during turn: {len(sets)-1}")
    print("   gone:", sorted(ids(before) - ids(win[-1] if win else before)), "new:", sorted(ids(win[-1] if win else before) - ids(before)))
    print(f"   after-window {len(after)} samples ({round(len(after)/5)}s); partly-offscreen: {offc}")
    print("   orion sc-orbit flags:", {k: sorted(v) for k, v in orbit.items()}, " x-extent:", xs)
