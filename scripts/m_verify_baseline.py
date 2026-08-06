"""Sub-project M — M-G0 基準忠實度的參考實作（spec §6.2）。

驗證從閉源 TradingView 腳本逆向工程出的 SL/TP 公式，對照 6 個洩漏樣本。
四項斷言 a/b/c/d 見 docs/superpowers/specs/2026-08-06-harmonic-pattern-design.md §6.2。

實作階段須把本檔轉為 tests/test_m_baseline_formula.py，並：
  - 從 scripts/m_config.py import SL_LEVEL_OVER_XA（不得複製常數，否則 M-G0a 的
    regression guard 形同虛設）；本檔在 m_config.py 建立前暫時硬編。
"""
import itertools
import json
import pathlib

import numpy as np

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests/fixtures/m_tv_baseline_samples.json"

# spec §4.5.2 凍結表。TODO(實作階段): 改為 from m_config import SL_LEVEL_OVER_XA
SL_LEVEL_OVER_XA = {
    "cypher": 1.0, "bat": 1.13, "shark": 1.272, "butterfly": 1.618, "deep_crab": 2.0,
    "gartley": 1.0, "alt_bat": 1.272, "crab": 2.0,          # fallback 推導，無觀測值
}
OBSERVED = {"cypher", "bat", "shark", "butterfly", "deep_crab"}
# spec §6.2 fixture 標籤 -> 形態鍵
LABEL_TO_KEY = {"Shark 113": "shark", "Deep Crab": "deep_crab", "Cypher": "cypher",
                "Bat": "bat", "Butterfly": "butterfly"}
STD_F, SHARK_F = (0.382, 0.618), (0.500, 0.886)
LADDER = [1.0, 1.13, 1.272, 1.618, 2.0]
# spec §4.2 各形態的名目 AD/XA 上界（Cypher 為推導值 0.728）
NOMINAL_AD_UPPER = {"gartley": 0.786, "bat": 0.886, "alt_bat": 1.13, "butterfly": 1.27,
                    "crab": 1.618, "deep_crab": 1.618, "shark": 1.13, "cypher": 0.728}


def reconstruct_rr(ad, ab, bc, xc, sl_level, f):
    """spec §6.2 的幾何重建：正規化到 X=0, A=1（bearish 鏡射後比例相同）。"""
    b = 1 - ab
    c = xc if xc is not None else (b + bc * ab if bc is not None else None)
    extreme = max([0.0, 1.0, b] + ([c] if c is not None else []))
    return f * abs(extreme - (1 - ad)) / abs(sl_level - ad)


def rr_interval(base, f, keys):
    """對每個 3 位小數的洩漏輸入施加 +-0.0005，回傳 RR 的可能區間。"""
    vals = []
    for combo in itertools.product([-5e-4, 0.0, 5e-4], repeat=len(keys)):
        p = dict(base)
        for k, dv in zip(keys, combo):
            p[k] = base[k] + dv
        vals.append(reconstruct_rr(f=f, **p))
    return min(vals), max(vals)


def main():
    d = json.load(open(FIXTURE))
    ok = True

    print("=== M-G0a: 凍結表的觀測條目 vs fixture ===")
    for s in d["samples"]:
        key = LABEL_TO_KEY[s["pattern"]]
        hit = SL_LEVEL_OVER_XA[key] == s["leaked_metrics"]["sl_level_over_xa"]
        ok &= hit
        print(f"  {s['id']:<28} {key:<10} 表={SL_LEVEL_OVER_XA[key]:<6} "
              f"fixture={s['leaked_metrics']['sl_level_over_xa']:<6} {'OK' if hit else 'MISMATCH'}")

    print("\n=== M-G0b: 捨入區間重疊判準（絕對容差對退化樣本不可達成）===")
    n_checks = n_pass = 0
    for s in d["samples"]:
        m, key = s["leaked_metrics"], LABEL_TO_KEY[s["pattern"]]
        base = dict(ad=m["ad_xa"], ab=m["ab_xa"], bc=m.get("bc_ab"),
                    xc=m.get("xc_xa"), sl_level=SL_LEVEL_OVER_XA[key])
        keys = [k for k in ("ad", "ab", "bc", "xc") if base[k] is not None]
        f1, f2 = SHARK_F if key == "shark" else STD_F
        for tag, f, leaked in (("RR1", f1, m["rr1"]), ("RR2", f2, m.get("rr2"))):
            if leaked is None:
                continue
            lo, hi = rr_interval(base, f, keys)
            llo, lhi = leaked - 0.005, leaked + 0.005     # 洩漏值本身只到 2 位小數
            hit = not (hi < llo or lo > lhi)
            n_checks += 1
            n_pass += hit
            ok &= hit
            print(f"  {s['id']:<28} {tag} 重建[{lo:8.4f},{hi:8.4f}] "
                  f"洩漏[{llo:7.3f},{lhi:7.3f}] {'OK' if hit else 'FAIL'}")
    print(f"  -> {n_pass}/{n_checks} 項 RR 檢定通過")

    print("\n=== M-G0c: 從絕對座標端到端推導（唯一不吃洩漏中間量的驗算）===")
    n_coord = 0
    for s in d["samples"]:
        p = {k: v["p"] for k, v in s["points"].items()}
        if any(v is None for v in p.values()):
            continue
        n_coord += 1
        m, bull = s["leaked_metrics"], s["direction"] == "bullish"
        xa = (p["A"] - p["X"]) if bull else (p["X"] - p["A"])
        ad = (p["A"] - p["D"]) / xa if bull else (p["D"] - p["A"]) / xa
        lvl = SL_LEVEL_OVER_XA[LABEL_TO_KEY[s["pattern"]]]
        sl_px = p["A"] - lvl * xa if bull else p["A"] + lvl * xa
        risk_pct = abs(p["D"] - sl_px) / p["D"] * 100
        d_ad, d_rp = abs(ad - m["ad_xa"]), abs(risk_pct - m["risk_pct"])
        hit = d_ad < 0.002 and d_rp < 0.01
        ok &= hit
        print(f"  {s['id']:<28} ad_xa {ad:.4f} vs {m['ad_xa']} (d={d_ad:.5f}) | "
              f"risk% {risk_pct:.4f} vs {m['risk_pct']} (d={d_rp:.5f}) {'OK' if hit else 'FAIL'}")
    assert n_coord == 2, f"預期 2 個有座標樣本，實得 {n_coord}"

    print("\n=== M-G0d: fallback 規則對觀測形態的重現率（斷言恰為 4/5）===")
    def fallback(up):
        return next((s for s in LADDER if s > up and abs(s - up) > 0.01), None)
    rep = 0
    for key in sorted(OBSERVED):
        fb, obs = fallback(NOMINAL_AD_UPPER[key]), SL_LEVEL_OVER_XA[key]
        rep += fb == obs
        print(f"  {key:<10} 名目上界={NOMINAL_AD_UPPER[key]:<6} fallback={fb:<6} "
              f"觀測={obs:<6} {'重現' if fb == obs else '例外'}")
    ok &= rep == 4
    print(f"  -> 重現 {rep}/5 {'(符合斷言)' if rep == 4 else '(不符斷言!)'}")

    print("\n=== spec §6.1: lower_95 數值錨例 ===")
    v = float(np.percentile(np.arange(10000) / 10000 - 0.2, 5.0))
    hit = abs(v - (-0.150005)) < 1e-9
    ok &= hit
    print(f"  percentile(arange(10000)/10000 - 0.2, 5.0) = {v:.9f}  預期 -0.150005  "
          f"{'OK' if hit else 'FAIL'}")

    print("\n=== spec §5.3: R_net 成本錨例 ===")
    entry, sl, exit_ = 100.0, 98.0, 103.0
    cost_abs = 0.00015 * entry + (0.00045 + 0.0001) * exit_
    r_net = (exit_ - entry) / abs(entry - sl) - cost_abs / abs(entry - sl)
    hit = abs(r_net - 1.464175) < 1e-9
    ok &= hit
    print(f"  R_net = {r_net:.6f}  預期 1.464175  {'OK' if hit else 'FAIL'}")

    print("\n=== spec §6.4: N_TRIALS_DECLARED ===")
    n = (8 + 1 + 1) * 4 * 3 * 2 * 2 + 2 + 2 + 2 + 1
    hit = n == 487
    ok &= hit
    print(f"  (8 形態 + 合併層 + selected 層) x4x3x2x2 + 消融2 + 端點2 + 半樣本2 + 成本1 "
          f"= {n}  預期 487  {'OK' if hit else 'FAIL'}")

    print("\n" + "=" * 46)
    print(f"M-G0 全部斷言: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
