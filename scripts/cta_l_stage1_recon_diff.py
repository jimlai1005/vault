#!/usr/bin/env python3
"""Cell-by-cell numeric diff v2: recon_output.md vs gates_table_t6.md,
keyed extraction (not positional zip -- v1 had an alignment bug from a
stray 'threshold: 1.3' line). Tolerance 1e-6. Read-only against
gates_table_t6.md; writes only to scratchpad."""
import re
from pathlib import Path

SCRATCH = Path("/private/tmp/claude-501/-Users-jim-projects-vault/083f97aa-8ce0-469a-b855-cbd455501c26/scratchpad")
T6_PATH = Path("/Users/jim/projects/vault/data/cache/cta_l/gates_table_t6.md")

recon_text = (SCRATCH / "recon_output.md").read_text()
t6_text = T6_PATH.read_text()


def norm_block(name: str) -> str:
    """Canonicalize a block header so '2020-09-14 .. 2021-12-31' (t6) and
    '2020-09-14..2021-12-31' (recon) collapse to the same key."""
    name = name.strip("# ").strip()
    name = re.sub(r"\s*\.\.\s*", "..", name)
    name = re.sub(r"\s*=\s*", "=", name)
    name = re.sub(r"\s+", " ", name)
    return name


def extract(text: str) -> dict:
    """Returns {(block, field): value} for every explicitly-labeled float."""
    out = {}
    block = "TOP"
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("###"):
            block = norm_block(line)
            continue
        if line.startswith("##"):
            block = norm_block(line)
            continue
        # "- B0: ann_ret=X mdd=Y MAR=Z"  or  "- V1: ann_ret=X mdd=Y MAR=Z"
        m = re.match(r"^-\s*(B0|V1)(?:\(cost15\))?:\s*(.+)$", line)
        if m:
            leg_raw, rest = m.group(1), m.group(2)
            leg = leg_raw
            for fm in re.finditer(r"([A-Za-z_]+)=(-?\d+\.\d+)", rest):
                out[(block, f"{leg}.{fm.group(1)}")] = float(fm.group(2))
            continue
        # generic "- <label>: <number>" (only if label contains no '=' sign
        # and is followed by exactly one trailing float)
        m2 = re.match(r"^-\s*\*{0,2}([^:=]+?)\*{0,2}:\s*(-?\d+\.\d+)\s*$", line)
        if m2:
            label = re.sub(r"\s+", " ", m2.group(1).strip())
            out[(block, label)] = float(m2.group(2))
    return out


recon_vals = extract(recon_text)
t6_vals = extract(t6_text)

# Map recon's slightly different labels/blocks onto t6's, where the two
# scripts used different English wording for the identical statistic.
LABEL_ALIASES = {
    "B0 annualized return": "B0 annualized return",
    "B0 MDD (signed, fraction)": "B0 MDD (signed, fraction)",
    "B0 MAR": "B0 MAR",
    "V1 annualized return": "V1 annualized return",
    "V1 MDD (signed, fraction)": "V1 MDD (signed, fraction)",
    "V1 MAR": "V1 MAR",
    "MAR(V1)/MAR(B0)": "MAR(V1)/MAR(B0)",
    "MAR(V1)/MAR(B0) at cost15": "MAR(V1)/MAR(B0) at cost15",
    "Sharpe(B0), point estimate": "point-estimate Sharpe(B0)",
    "Sharpe(V1), point estimate": "point-estimate Sharpe(V1)",
    "delta-Sharpe, point estimate": "point-estimate ΔSharpe (V1 - B0)",
}
BLOCK_ALIASES = {
    "G-L1 (recomputed with fixed-base MDD)": "G-L1: full-window MAR ratio",
    "G-L4 (recomputed with fixed-base MDD)": "G-L4: cost x1.5 (0.0825%/side) — repeat G-L1 rule",
    "G-L3 sanity (Sharpe point estimates, MDD-independent)": "G-L3: paired stationary block bootstrap on ΔSharpe (90% CI)",
}


def canon_key(block, label):
    b = BLOCK_ALIASES.get(block, block)
    l = LABEL_ALIASES.get(label, label)
    return (b, l)


recon_canon = {canon_key(b, l): v for (b, l), v in recon_vals.items()}

matched, mismatched, recon_only = [], [], []
for (b, l), v in recon_canon.items():
    if (b, l) in t6_vals:
        tv = t6_vals[(b, l)]
        resid = abs(v - tv)
        (matched if resid <= 1e-6 else mismatched).append((b, l, v, tv, resid))
    else:
        recon_only.append((b, l, v))

t6_only = [(b, l, v) for (b, l), v in t6_vals.items() if (b, l) not in recon_canon]

print(f"recon fields extracted: {len(recon_vals)}")
print(f"t6 fields extracted:    {len(t6_vals)}")
print(f"\nmatched within 1e-6: {len(matched)}")
print(f"mismatched (>1e-6):  {len(mismatched)}")
print(f"recon-only (no t6 counterpart -- G-L2 doesn't emit fold-pass count "
      f"in recon; expected, not a numeric disagreement): {len(recon_only)}")
print(f"t6-only (t6 fields recon's script never computes -- G-L2 fold-pass "
      f"count, G-L3 bootstrap distribution mean/std/CI, G-L4/G-L5 boolean "
      f"direction flags, threshold constants -- expected, not numeric "
      f"disagreements since recon deliberately only re-derives the "
      f"MDD-dependent statistics): {len(t6_only)}")

print("\n=== MATCHED (<=1e-6) ===")
for b, l, v, tv, resid in matched:
    print(f"  OK   [{b}] {l}: recon={v:.12f}  t6={tv:.12f}  resid={resid:.2e}")

print("\n=== MISMATCHED (>1e-6) ===")
if not mismatched:
    print("  (none)")
for b, l, v, tv, resid in mismatched:
    print(f"  DIFF [{b}] {l}: recon={v:.12f}  t6={tv:.12f}  resid={resid:.2e}")

print("\n=== recon-only fields (not compared) ===")
for b, l, v in recon_only:
    print(f"  {b} :: {l} = {v}")

print("\n=== t6-only fields (not compared -- outside MDD-swap scope) ===")
for b, l, v in t6_only:
    print(f"  {b} :: {l} = {v}")
