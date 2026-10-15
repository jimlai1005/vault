"""Mechanical QA over the drafted wallet reports.

Checks that do NOT rely on the writing agent's own say-so (rules/judgment.md: a subagent's
report is not evidence). For each draft:
  1. file exists and is non-trivial
  2. all six required sections present and non-empty
  3. frontmatter has address + proposed_filename; filename shape matches the house convention
     `hl-0x????...????-<phrase>.md` where the prefix is 6 chars INCLUDING "0x"
  4. the address in the frontmatter really is this wallet
  5. "信心有限" appears (section 5 honesty requirement)
  6. numeric traceability sample: pull the large numbers out of the draft and report what
     fraction of them appear verbatim in the wallet's analysis.txt (derived ratios legitimately
     will not, so this is a signal, not a gate — low scores get eyeballed)

Usage: python check_drafts.py
"""
import pathlib, re, sys, json

ROOT = pathlib.Path(__file__).parent.parent
DRAFTS = ROOT / "drafts"
DATA = ROOT / "data"
SECTIONS = ["1 帳戶概況", "2 交易機制", "3 大波動日", "4 持倉時間", "5 可複製性", "6 資料極限"]
# optional "NN-" copy-score prefix (2026-09-24 pilot: 00- = failed gate, otherwise the rounded score)
FNAME_RE = re.compile(r"^(?:\d{2}-)?hl-0x[0-9a-fA-F]{4}\.\.\.[0-9a-fA-F]{4}-.+\.md$")

addrs = (ROOT / "addrs.txt").read_text().split()
rows, problems = [], []
for a in addrs:
    s = a[:10]
    p = DRAFTS / f"{s}.md"
    if not p.exists():
        problems.append(f"{s}: MISSING draft")
        continue
    txt = p.read_text()
    r = {"w": s, "bytes": len(txt)}

    # sections present AND non-empty (at least 120 chars before the next "## ")
    missing, thin = [], []
    for sec in SECTIONS:
        m = re.search(rf"^##\s+{re.escape(sec)}\s*$", txt, re.M)
        if not m:
            missing.append(sec)
            continue
        nxt = re.search(r"^##\s+", txt[m.end():], re.M)
        body = txt[m.end(): m.end() + (nxt.start() if nxt else len(txt))]
        if len(body.strip()) < 120:
            thin.append(sec)
    r["missing"] = missing
    r["thin"] = thin
    if missing:
        problems.append(f"{s}: missing sections {missing}")
    if thin:
        problems.append(f"{s}: thin sections {thin}")

    # frontmatter
    fn = re.search(r"^proposed_filename:\s*\"?([^\"\n]+)\"?\s*$", txt, re.M)
    r["fname"] = fn.group(1).strip() if fn else None
    if not fn:
        problems.append(f"{s}: no proposed_filename")
    else:
        v = r["fname"]
        if not FNAME_RE.match(v):
            problems.append(f"{s}: filename shape wrong -> {v}")
        elif not ((core := re.sub(r"^\d{2}-", "", v))[3:9].lower() == a[:6].lower() and core[12:16].lower() == a[-4:].lower()):
            problems.append(f"{s}: filename prefix/suffix does not match address -> {v}")
        if re.search(r"20\d\d", v):
            problems.append(f"{s}: filename contains a date -> {v}")

    ad = re.search(r"^address:\s*\"?(0x[0-9a-fA-F]{40})\"?", txt, re.M)
    if not ad or ad.group(1).lower() != a.lower():
        problems.append(f"{s}: frontmatter address missing/wrong")

    r["confidence"] = "信心有限" in txt
    if not r["confidence"]:
        problems.append(f"{s}: missing 信心有限")

    # data-limit keywords
    for kw in ("TWAP", "DRIFT", "funding"):
        if kw not in txt:
            problems.append(f"{s}: section 6 keyword missing: {kw}")

    # numeric traceability
    src = (DATA / s / "analysis.txt").read_text()
    src_nums = set(re.findall(r"-?[\d,]+(?:\.\d+)?", src))
    src_plain = {n.replace(",", "") for n in src_nums}
    nums = [n for n in re.findall(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?![\w])", txt)]
    hit = sum(1 for n in nums if n in src_nums or n.replace(",", "") in src_plain)
    r["nums"] = len(nums)
    r["hit"] = hit
    r["rate"] = hit / len(nums) if nums else 0.0
    rows.append(r)

print(f"{'wallet':<12}{'bytes':>7}{'sections':>10}{'信心有限':>9}{'big nums':>10}{'traceable':>11}  proposed_filename")
for r in rows:
    ok = "OK" if not r["missing"] and not r["thin"] else f"{len(r['missing'])}m/{len(r['thin'])}t"
    print(f"{r['w']:<12}{r['bytes']:>7}{ok:>10}{'yes' if r['confidence'] else 'NO':>9}"
          f"{r['nums']:>10}{r['rate']:>10.0%}  {r['fname']}")
print(f"\ndrafts found: {len(rows)}/{len(addrs)}")
print(f"problems: {len(problems)}")
for p in problems:
    print("  !", p)
