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
import sys

import numpy as np

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests/fixtures/m_tv_baseline_samples.json"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import m_config as cfg

# spec §6.2 fixture 標籤 -> 形態鍵
LABEL_TO_KEY = {"Shark 113": "shark", "Deep Crab": "deep_crab", "Cypher": "cypher",
                "Bat": "bat", "Butterfly": "butterfly"}

SL_LEVEL_OVER_XA = cfg.SL_LEVEL_OVER_XA
OBSERVED = cfg.OBSERVED_SL_PATTERNS
STD_F, SHARK_F = cfg.TP_FACTORS, cfg.TP_FACTORS_SHARK
LADDER = list(cfg.SL_LADDER)
NOMINAL_AD_UPPER = cfg.NOMINAL_AD_UPPER


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

    print("\n=== spec §4.5.4: 分批出場 R_net 錨例 ===")
    print("  擋的誤讀是『進場費先 50/50 分攤到每腿、再各加權 0.5』（fee_in 被乘 0.5 兩次）；")
    print("  『每腿各扣【全額】成本再加權 0.5』則等於正確值，是合法的等價寫法。")
    e2, sl2, x1, x2 = 100.0, 98.0, 101.0, 102.0
    risk2 = abs(e2 - sl2)
    gross = 0.5 * (x1 - e2) / risk2 + 0.5 * (x2 - e2) / risk2
    cost2 = 0.00015 * e2 + 0.5 * (0.00045 + 0.0001) * x1 + 0.5 * (0.00045 + 0.0001) * x2
    r_batch = gross - cost2 / risk2
    # 誤讀版：fee_in 先 50/50 分攤到每腿，再對每腿加權 0.5 -> fee_in 被乘 0.5 兩次
    bad = sum(0.5 * ((px - e2) - (0.5 * 0.00015 * e2 + (0.00045 + 0.0001) * px)) / risk2
              for px in (x1, x2))
    # 等價寫法：每腿各扣【全額】成本再加權 0.5，應等於正確值
    equiv = sum(0.5 * ((px - e2) - (0.00015 * e2 + (0.00045 + 0.0001) * px)) / risk2
                for px in (x1, x2))
    assert abs(equiv - 0.7145875) < 1e-9, "等價寫法應得同一個值"
    hit = abs(r_batch - 0.7145875) < 1e-9 and abs(bad - r_batch) > 1e-6
    ok &= hit
    print(f"  R_net = {r_batch:.7f}  預期 0.7145875 | 誤讀版 = {bad:.7f} "
          f"(差 {abs(r_batch - bad):.7f} R)  {'OK' if hit else 'FAIL'}")

    print("\n=== spec §6.3/§6.4: 試驗數 ===")
    n_obs = (8 + 1 + 1) * 4 * 3 * 2 * 2
    n = n_obs + 2 + 2 + 2 + 1
    hit = n_obs == 480 and n == 487
    ok &= hit
    print(f"  N_OBSERVABLE_TRIALS = (8 形態 + 合併層 + selected 層) x4x3x2x2 = {n_obs}  預期 480")
    print(f"  N_TRIALS_DECLARED   = {n_obs} + 消融2 + 端點2 + 半樣本2 + 成本1 = {n}  預期 487  "
          f"{'OK' if hit else 'FAIL'}")

    print("\n=== spec §6.3: sr_star 對 sr_list 組成的敏感度（B4 的量化依據）===")
    g = 0.5772156649
    from scipy import stats as _st
    coef = (1 - g) * _st.norm.ppf(1 - 1 / n) + g * _st.norm.ppf(1 - 1 / (n * np.e))
    hit = abs(coef - 3.0446) < 1e-3
    ok &= hit
    print(f"  sr_star = {coef:.4f} x sd(sr_list)  預期 ~3.0446  {'OK' if hit else 'FAIL'}")
    print(f"    sd=0.008 (只放 48 個合併層 cell) -> sr_star={coef*0.008:.4f}")
    print(f"    sd=0.040 (放全部 480 個 cell)    -> sr_star={coef*0.040:.4f}")
    print("    日 Sharpe 約 0.03-0.06 -> 組成必須釘死，否則 M-G4 必過或必不過與策略無關")

    print("\n" + "=" * 46)
    print(f"M-G0 全部斷言: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
