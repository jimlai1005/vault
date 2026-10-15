"""Rebuild the report table in pandora/wallets/INDEX.md, sorted by copy-trade score.

Owner decision 2026-09-24: scores do not go in filenames; the INDEX is the ranking the owner reads.
Rows come from the existing INDEX (their 型態／結論 text is kept verbatim) joined to each wallet's
copyscore.json (from every batch dir given). Reports in pandora that belong to a given batch but have
no INDEX row yet are appended automatically (2026-09-25, batch B: 284 new reports): 型態 = the strategy
phrase from the filename, 結論 = the report's one-sentence summary (the paragraph right before "## 1").
Order (spec v0.6 §1.6): gate PASS → scored FAIL → 樣本不足 → 無法評分, each by total desc; reports with
no score go to a separate「尚未評分」section at the end.

Usage: python index_table.py <batch_dir> [<batch_dir> ...]   (writes INDEX.md in place, backup alongside)
"""
import json, pathlib, re, sys, datetime

INDEX = pathlib.Path("/Users/jim/projects/obsidian/pandora/wallets/INDEX.md")
PANDORA = INDEX.parent
SUMMARY_MAX = 110


def scores(batch_dirs):
    out = {}
    for b in batch_dirs:
        for j in pathlib.Path(b, "data").glob("0x*/copyscore.json"):
            d = json.load(open(j))
            addr = (d.get("addr") or "").lower()
            if not addr:
                continue
            gate = d.get("gate", {}) or {}
            sample = d.get("sample") or {}
            out[addr] = {"total": int(d.get("total") or 0),
                         "pass": bool(gate.get("overall")) if isinstance(gate.get("overall"), bool) else str(gate.get("overall")).upper() == "PASS",
                         "unscorable": bool(d.get("unscorable")),
                         "insufficient": sample.get("sufficient") is False,
                         "stopout": d.get("stopout_date")}
    return out


def report_address(fn):
    p = PANDORA / (fn + ".md")
    if not p.exists():
        return None
    m = re.search(r'^address:\s*"?(0x[0-9a-fA-F]{40})"?', p.read_text(), re.M)
    return m.group(1).lower() if m else None


def esc(s):
    return s.replace("|", "\\|").strip()


def new_row_cells(path):
    """cells (without score) for a pandora report that has no INDEX row yet"""
    text = path.read_text()
    stem = path.stem
    addr = re.search(r'^address:\s*"?(0x[0-9a-fA-F]{40})', text, re.M).group(1)
    short = f"{addr[:6]}…{addr[-4:]}"
    phrase = re.sub(r"^hl-0x[0-9a-fA-F]{4}\.\.\.[0-9a-fA-F]{4}-", "", stem)
    body = text.split("\n## 1 ", 1)[0]
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    summary = ""
    for p in reversed(paras):   # the one-liner is the last plain paragraph before chapter 1
        if not p.startswith(("#", "|", "<!--", "(1)", "---")):
            summary = " ".join(p.split())
            break
    if len(summary) > SUMMARY_MAX:
        summary = summary[:SUMMARY_MAX].rstrip() + "…"
    link = f"[[wallets/{stem}\\|{short} {esc(phrase)}]]"
    return [f" {link} ", f" `{short}` ", f" {esc(phrase)} ", f" {esc(summary)} "], addr.lower()


def main(batch_dirs):
    txt = INDEX.read_text()
    INDEX.with_name(f"INDEX.md.bak-{datetime.date.today()}").write_text(txt)
    m = re.search(r"(## 報告\n\n)(.*?)(?=\n0x9264、0x9046)", txt, re.S)
    if not m:
        raise SystemExit("report block not found")
    head = m.group(1)
    rows = [r for r in m.group(2).splitlines() if "[[wallets/" in r]
    sc = scores(batch_dirs)

    entries = []          # (addr, cells-without-score)
    seen = set()
    for r in rows:
        fn = re.search(r"\[\[wallets/([^|\\\]]+)", r).group(1)
        addr = report_address(fn)
        cells = re.split(r"(?<!\\)\|", r.rstrip("|"))[1:]   # split on unescaped pipes only ("\|" lives inside wikilinks)
        if len(cells) == 5:      # strip a score cell added by a previous run
            cells = cells[1:]
        entries.append((addr, cells))
        if addr:
            seen.add(addr)
    added = 0
    for b in batch_dirs:
        batch_name = pathlib.Path(b).name
        for p in sorted(PANDORA.glob("hl-*.md")):
            t = p.read_text()
            if f"reports/{batch_name}/" not in t:
                continue
            cells, addr = new_row_cells(p)
            if addr in seen:
                continue
            entries.append((addr, cells)); seen.add(addr); added += 1

    scored, unscored = [], []
    for addr, cells in entries:
        s = sc.get(addr) if addr else None
        if s:
            if s["unscorable"]:
                tag, key = "無法評分", (3, 0)
            elif s["pass"]:
                tag, key = f"**{s['total']}** ✅", (0, -s["total"])
            elif s["insufficient"]:
                tag, key = f"{s['total']}（樣本不足）", (2, -s["total"])
            else:
                tag, key = f"{s['total']}" + ("（爆倉）" if s["stopout"] else ""), (1, -s["total"])
            scored.append((key, f"| {tag} |" + "|".join(cells) + "|"))
        else:
            unscored.append(f"| — |" + "|".join(cells) + "|")
    scored.sort(key=lambda x: x[0])
    new_hdr = "| 跟單評分 | 檔案 | 對象 | 型態 | 結論 |\n|---|---|---|---|---|\n"
    new_body = "\n".join(r for _, r in scored) + "\n"
    tail = ""
    if unscored:
        tail = ("\n### 尚未評分\n\n" + new_hdr + "\n".join(unscored) + "\n")
    note = ("依**跟單評分**排序（規格 vault `docs/plans/copytrade-score.md` v0.6）：通過門檻者在前（✅），"
            "其後為未通過者依分數遞減；「樣本不足」＝perp 事件 <50 或 leader 淨損益過小，分數僅供參考、排在未通過者之後；"
            "「無法評分」＝無永續成交或權益過小；「爆倉」＝模擬跟單者在全歷史重放中權益歸零。"
            "分數只在這裡與各報告的「## 0」區塊，不放檔名。\n\n")
    txt = txt[:m.start()] + head + note + new_hdr + new_body + tail + txt[m.end():]
    INDEX.write_text(txt)
    print(f"rows: scored={len(scored)} unscored={len(unscored)} added={added}; "
          f"pass={sum(1 for k,_ in scored if k[0]==0)} insufficient={sum(1 for k,_ in scored if k[0]==2)} "
          f"unscorable={sum(1 for k,_ in scored if k[0]==3)}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["/Users/jim/projects/vault/reports/wallets-batch-2026-09"])
