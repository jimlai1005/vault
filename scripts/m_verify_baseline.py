import json
FX = '/Users/jim/projects/vault/tests/fixtures/m_tv_baseline_samples.json'
d = json.load(open(FX))

SL_LEVEL = {"Cypher":1.0, "Bat":1.13, "Shark 113":1.272, "Butterfly":1.618, "Deep Crab":2.0}
SHARK_F, STD_F = (0.5, 0.886), (0.382, 0.618)
ok_all = True

print("=== M-G0a: 凍結表的 5 個觀測條目 vs fixture ===")
for s in d['samples']:
    lv = s['leaked_metrics'].get('sl_level_over_xa')
    exp = SL_LEVEL.get(s['pattern'])
    if exp is None: continue
    m = (lv == exp); ok_all &= m
    print(f"  {s['pattern']:<12} 表={exp:<6} fixture={lv:<6} {'OK' if m else 'MISMATCH'}")

print("\n=== M-G0b/c: 幾何重建 + 凍結 SL 表，6 個樣本全驗 ===")
print(f"{'sample':<28} {'ext':>4} {'f1':>6} {'RR1算':>9} {'RR1洩':>7} {'RR2算':>9} {'RR2洩':>7}  ?")
npass = 0
for s in d['samples']:
    m = s['leaked_metrics']; ad = m['ad_xa']; sl = SL_LEVEL[s['pattern']]
    ab = m.get('ab_xa')
    B = 1 - ab
    C = m['xc_xa'] if m.get('xc_xa') is not None else (B + m['bc_ab']*ab if m.get('bc_ab') is not None else None)
    cands = [0.0, 1.0, B] + ([C] if C is not None else [])
    extreme = max(cands); D = 1 - ad
    risk, leg = abs(sl - ad), abs(extreme - D)
    f1, f2 = SHARK_F if 'Shark' in s['pattern'] else STD_F
    r1, r2 = f1*leg/risk, f2*leg/risk
    p1 = abs(r1 - m['rr1']) < 0.01
    p2 = (m.get('rr2') is None) or abs(r2 - m['rr2']) < 0.01
    npass += (p1 and p2); ok_all &= (p1 and p2)
    which = 'C' if C is not None and abs(extreme-C)<1e-12 else ('A' if abs(extreme-1.0)<1e-12 else '?')
    print(f"{s['id']:<28} {which:>4} {f1:>6} {r1:>9.4f} {m['rr1']:>7.2f} {r2:>9.4f} "
          f"{(m['rr2'] if m.get('rr2') is not None else float('nan')):>7.2f}  {'PASS' if p1 and p2 else 'FAIL'}")
print(f"-> M-G0b: {npass}/6")

print("\n=== M-G0d: fallback 規則對 5 個觀測形態的重現率（應為 4/5，Bat 例外） ===")
S = [1.0, 1.13, 1.272, 1.618, 2.0]
NOMINAL_UP = {"Gartley":0.786, "Bat":0.886, "Alternate Bat":1.13, "Butterfly":1.27,
              "Crab":1.618, "Deep Crab":1.618, "Shark 113":1.13, "Cypher":0.728, "5-0":None}
def fallback(up):
    if up is None: return 1.0
    return next((s for s in S if s > up and abs(s-up) > 0.01), None)   # 1.27≈1.272 視為相等
rep = 0
for pat, obs in SL_LEVEL.items():
    fb = fallback(NOMINAL_UP[pat]); hit = (fb == obs); rep += hit
    print(f"  {pat:<12} 名目上界={NOMINAL_UP[pat]:<6} fallback={fb:<6} 觀測={obs:<6} {'重現' if hit else '例外'}")
print(f"-> 重現 {rep}/5 {'(符合 M-G0d 斷言)' if rep == 4 else '(不符 M-G0d！)'}")
ok_all &= (rep == 4)
print("\n  推導 4 個形態的檔位:", {p: fallback(NOMINAL_UP[p]) for p in ("Gartley","Alternate Bat","Crab","5-0")})

print("\n=== §5.3 成本錨例 ===")
Pe, Ps, Px = 100.0, 98.0, 103.0
Rg = (Px-Pe)/abs(Pe-Ps)
cost_abs = 0.00015*Pe + (0.00045+0.0001)*Px
Rn = Rg - cost_abs/abs(Pe-Ps)
print(f"  R_gross={Rg}  cost_abs={cost_abs:.6f}  cost_R={cost_abs/2:.6f}  R_net={Rn:.6f}")
m = abs(Rn - 1.464175) < 1e-9; ok_all &= m
print(f"  spec 宣稱 1.464175 -> {'OK' if m else 'MISMATCH'}")

print("\n=== §6.4 試驗數 ===")
n = 10*4*3*2*2 + 2
print(f"  10*4*3*2*2 + 2 = {n}  spec 宣稱 482 -> {'OK' if n==482 else 'MISMATCH'}")
ok_all &= (n == 482)
print(f"\n{'='*40}\n全部驗證: {'PASS' if ok_all else 'FAIL'}")
