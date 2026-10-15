"""T2: read every data/<addr10>/copyscore.json -> data/_ranking.txt + data/_ranking.json.

Sort rule (plan §3): gate-passed wallets first (each internally by total desc),
then gate-failed wallets after (each internally by total desc).

Usage: python rank.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"
addrs = (ROOT / "addrs.txt").read_text().split()

rows, missing = [], []
for a in addrs:
    s = a[:10]
    p = DATA / s / "copyscore.json"
    if not p.exists():
        log = ROOT / "logs" / f"copyscore_{s}.log"
        reason = "copyscore.json not found"
        if log.exists():
            tail = log.read_text().splitlines()[-3:]
            reason += " | log tail: " + " / ".join(tail)
        missing.append({"addr10": s, "reason": reason, "log": str(log)})
        continue
    d = json.loads(p.read_text())
    unscorable = bool(d.get("unscorable"))
    rows.append({
        "addr10": s,
        "addr": d.get("addr", a),
        "unscorable": unscorable,
        "gate": bool(d["gate"]["overall"]),
        "total": d["total"],
        "D1": round(d["D1"]["score"], 2), "D2": round(d["D2"]["score"], 2),
        "D3": round(d["D3"]["score"], 2), "D4": round(d["D4"]["score"], 2), "D5": round(d["D5"]["score"], 2),
        "r_normal": d["D1"]["r_normal"], "r_stress_worst": d["D1"]["r_stress"]["worst"],
        "r_miss_worst": d["D1"]["r_miss"]["worst"],
        "mdd": d["D2"]["mdd"], "lev_peak": d["D2"]["lev_peak"],
        "conc": d["D3"]["conc"], "E0": d.get("E0"), "window_days": d["window"]["days"],
        "spec_version": d.get("spec_version"),
        "unscorable_reason": d.get("unscorable_reason"),
    })

# plan v0.4 §0: unscorable wallets ("無法評分：權益過小") always rank last, below
# every scored wallet (pass or fail) regardless of total (all are total=0 anyway).
rows.sort(key=lambda r: (0 if r["gate"] else (1 if not r["unscorable"] else 2), -r["total"]))

lines = []
lines.append(f"{'rk':>3} {'addr10':<12}{'gate':>6}{'total':>7}{'D1':>7}{'D2':>7}{'D3':>7}{'D4':>7}{'D5':>7}"
             f"{'r_norm':>9}{'r_strs':>9}{'r_miss':>9}{'mdd':>9}{'lev':>9}{'conc':>8}")
for i, r in enumerate(rows, 1):
    gate_label = "无法评分" if r["unscorable"] else ("PASS" if r["gate"] else "FAIL")
    if r["unscorable"]:
        lines.append(f"{i:>3} {r['addr10']:<12}{gate_label:>8}{r['total']:>5}  (E_min/L_peak in JSON) -- {r['unscorable_reason']}")
        continue
    lev_str = f"{r['lev_peak']:>8.2f}x" if r["lev_peak"] is not None else "  equity=0"
    lines.append(f"{i:>3} {r['addr10']:<12}{gate_label:>6}{r['total']:>7}"
                 f"{r['D1']:>7}{r['D2']:>7}{r['D3']:>7}{r['D4']:>7}{r['D5']:>7}"
                 f"{r['r_normal']:>9.3f}{r['r_stress_worst']:>9.3f}{r['r_miss_worst']:>9.3f}"
                 f"{r['mdd']:>9.2%}{lev_str:>9}{r['conc']:>8.3f}")
lines.append("")
lines.append(f"scored: {len(rows)}/{len(addrs)}  missing: {len(missing)}")
for m in missing:
    lines.append(f"  ! {m['addr10']}: {m['reason']}")

(DATA / "_ranking.txt").write_text("\n".join(lines) + "\n")
(DATA / "_ranking.json").write_text(json.dumps({"rows": rows, "missing": missing}, indent=2, sort_keys=True))

print("\n".join(lines))
print(f"\nwrote {DATA/'_ranking.txt'} and {DATA/'_ranking.json'}")
