"""Rebuild the report table in pandora/wallets/INDEX.md, sorted by copy-trade score.

Owner decision 2026-09-24: scores do not go in filenames; the INDEX is the ranking the owner reads.
Rows come from the existing INDEX (their 型態／結論 text is kept verbatim) joined to each wallet's
copyscore.json (from every batch dir given). Order: gate PASS first, then scored FAIL, then unscorable,
each by total desc; reports with no score go to a separate「尚未評分」section at the end.

Usage: python index_table.py <batch_dir> [<batch_dir> ...]   (writes INDEX.md in place, backup alongside)
"""
import json, pathlib, re, sys, datetime

INDEX = pathlib.Path("/Users/jim/projects/obsidian/pandora/wallets/INDEX.md")
PANDORA = INDEX.parent


def scores(batch_dirs):
    out = {}
    for b in batch_dirs:
        for j in pathlib.Path(b, "data").glob("0x*/copyscore.json"):
            d = json.load(open(j))
            addr = (d.get("addr") or "").lower()
            if not addr:
                continue
            gate = d.get("gate", {}) or {}
            out[addr] = {"total": int(d.get("total") or 0),
                         "pass": bool(gate.get("overall")) if isinstance(gate.get("overall"), bool) else str(gate.get("overall")).upper() == "PASS",
                         "unscorable": bool(d.get("unscorable")),
                         "stopout": d.get("stopout_date")}
    return out


def report_address(fn):
    m = re.search(r'^address:\s*"?(0x[0-9a-fA-F]{40})"?', (PANDORA / (fn + ".md")).read_text(), re.M)
    return m.group(1).lower() if m else None


def main(batch_dirs):
    txt = INDEX.read_text()
    INDEX.with_name(f"INDEX.md.bak-{datetime.date.today()}").write_text(txt)
    # the whole report block: from "## 報告" to the funder-note paragraph that follows the table(s).
    # every line in it that carries a wikilink is a report row (already-ranked rows start with a score cell)
    m = re.search(r"(## 報告\n\n)(.*?)(?=\n0x9264、0x9046)", txt, re.S)
    if not m:
        raise SystemExit("report block not found")
    head = m.group(1)
    rows = [r for r in m.group(2).splitlines() if "[[wallets/" in r]
    sc = scores(batch_dirs)
    scored, unscored = [], []
    for r in rows:
        fn = re.search(r"\[\[wallets/([^|\\\]]+)", r).group(1)
        addr = report_address(fn)
        s = sc.get(addr) if addr else None
        cells = re.split(r"(?<!\\)\|", r.rstrip("|"))[1:]   # split on unescaped pipes only ("\|" lives inside wikilinks)
        # strip any score cell added by a previous run (first cell looks like "**44** …" or "—")
        if len(cells) == 5:
            cells = cells[1:]
        if s:
            if s["unscorable"]:
                tag, key = "無法評分", (2, 0)
            elif s["pass"]:
                tag, key = f"**{s['total']}** ✅", (0, -s["total"])
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
    note = ("依**跟單評分**排序（規格 vault `docs/plans/copytrade-score.md` v0.5）：通過門檻者在前（✅），"
            "其後為未通過者依分數遞減；「爆倉」＝模擬跟單者在全歷史重放中權益歸零。分數只在這裡與各報告的「## 0」區塊，不放檔名。\n\n")
    txt = txt[:m.start()] + head + note + new_hdr + new_body + tail + txt[m.end():]
    INDEX.write_text(txt)
    print(f"rows: scored={len(scored)} unscored={len(unscored)}; pass={sum(1 for k,_ in scored if k[0]==0)}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["/Users/jim/projects/vault/reports/wallets-batch-2026-09"])
