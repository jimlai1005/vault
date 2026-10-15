"""T2: read every data/<addr10>/copyscore.json -> data/_ranking.txt + data/_ranking.json.

Sort rule (plan §3, extended by v0.6 §1.6): gate-passed + sample-sufficient wallets
first (tier 0, internally by total desc), then gate-failed + sample-sufficient (tier
1, by total desc), then sample-insufficient wallets regardless of gate result (tier
2, "樣本不足" — demoted because the perp-only simulation isn't trustworthy on too
little activity, by total desc), then fully-unscorable wallets last (tier 3, either
"no day reaches E_min" or "no perp fills" — both have unscorable:true).

Usage: python rank.py
"""
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"
addrs = (ROOT / "addrs.txt").read_text().split()

TIER_LABELS = {0: "PASS", 1: "FAIL", 2: "樣本不足", 3: "無法評分"}

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
    sample = d.get("sample") or {}
    # a copyscore.json that predates v0.6 and was never backfilled has no `sample`
    # key at all -- fail open (treat as sufficient) rather than silently demoting it.
    sample_sufficient = bool(sample.get("sufficient", True))
    gate = bool(d.get("gate", {}).get("overall", False))
    total = d.get("total")
    if total is None:
        total = 0

    if unscorable:
        tier = 3
    elif not sample_sufficient:
        tier = 2
    elif gate:
        tier = 0
    else:
        tier = 1

    row = {
        "addr10": s,
        "addr": d.get("addr", a),
        "unscorable": unscorable,
        "gate": gate,
        "total": total,
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "sample_perp_events": sample.get("perp_events"),
        "sample_leader_net": sample.get("leader_net"),
        "sample_sufficient": sample_sufficient,
        "E0": d.get("E0"), "window_days": d.get("window", {}).get("days"),
        "spec_version": d.get("spec_version"),
        "unscorable_reason": d.get("unscorable_reason") or d.get("reason"),
    }
    if "D1" in d:
        row.update({
            "D1": round(d["D1"]["score"], 2), "D2": round(d["D2"]["score"], 2),
            "D3": round(d["D3"]["score"], 2), "D4": round(d["D4"]["score"], 2), "D5": round(d["D5"]["score"], 2),
            "r_normal": d["D1"]["r_normal"], "r_stress_worst": d["D1"]["r_stress"]["worst"],
            "r_miss_worst": d["D1"]["r_miss"]["worst"],
            "mdd": d["D2"]["mdd"], "lev_peak": d["D2"]["lev_peak"],
            "conc": d["D3"]["conc"],
        })
    rows.append(row)

rows.sort(key=lambda r: (r["tier"], -r["total"]))

lines = []
lines.append(f"{'rk':>3} {'addr10':<12}{'tier':>10}{'total':>7}{'D1':>7}{'D2':>7}{'D3':>7}{'D4':>7}{'D5':>7}"
             f"{'r_norm':>9}{'r_strs':>9}{'r_miss':>9}{'mdd':>9}{'lev':>9}{'conc':>8}")
for i, r in enumerate(rows, 1):
    label = r["tier_label"]
    if "D1" not in r:
        lines.append(f"{i:>3} {r['addr10']:<12}{label:>10}{'--':>7}  -- {r['unscorable_reason'] or ''}")
        continue
    lev_str = f"{r['lev_peak']:>8.2f}x" if r["lev_peak"] is not None else "  equity=0"
    extra = ""
    if r["tier"] == 2:
        extra = (f"  [樣本不足: perp_events={r['sample_perp_events']} "
                 f"leader_net=${r['sample_leader_net']:,.0f}]")
    lines.append(f"{i:>3} {r['addr10']:<12}{label:>10}{r['total']:>7}"
                 f"{r['D1']:>7}{r['D2']:>7}{r['D3']:>7}{r['D4']:>7}{r['D5']:>7}"
                 f"{r['r_normal']:>9.3f}{r['r_stress_worst']:>9.3f}{r['r_miss_worst']:>9.3f}"
                 f"{r['mdd']:>9.2%}{lev_str:>9}{r['conc']:>8.3f}{extra}")
lines.append("")
lines.append(f"scored: {len(rows)}/{len(addrs)}  missing: {len(missing)}")
for m in missing:
    lines.append(f"  ! {m['addr10']}: {m['reason']}")

tier_counts = Counter(r["tier"] for r in rows)
lines.append("")
lines.append("tier counts: " + "  ".join(f"{TIER_LABELS[t]}={tier_counts.get(t, 0)}" for t in (0, 1, 2, 3)))

(DATA / "_ranking.txt").write_text("\n".join(lines) + "\n")
(DATA / "_ranking.json").write_text(json.dumps({"rows": rows, "missing": missing}, indent=2, sort_keys=True))

print("\n".join(lines))
print(f"\nwrote {DATA/'_ranking.txt'} and {DATA/'_ranking.json'}")
