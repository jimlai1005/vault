"""Turn a verified draft into the reader-facing pandora report.

The drafts carry `[A]`..`[E]` source markers so check_drafts.py can trace every number back
to analysis.txt. Those markers are verification scaffolding, not report content (decided with
the owner 2026-09-24: body stays in the house style of the older reports; traceability is one
line at the end of section 6). This script:

  1. drops the 出處 column from tables whose header ends with it (prose in that cell is folded
     back into the value cell — a caveat once lived there)
  2. inside every parenthetical that carried a marker: removes the marker, then removes any
     comma-separated SEGMENT that is nothing but a reference to analysis.txt (section names,
     field names, "見"/"來源"/"算式" stumps, "10 worst episodes 第 7 行" pointers). Segments with
     real content (digits, ordinary prose) survive. An emptied parenthetical is dropped whole.
  3. removes marker fragments left in plain prose / table cells
  4. drops the `proposed_filename:` frontmatter line
  5. appends the traceability line to section 6 (before `## 相關`)

Guards printed per file by --all:
  residual     = lines still containing a marker (must be 0)
  lost_parens  = marker-free parentheticals of the draft missing from the output (must be 0;
                 nesting-aware, so "(win)" inside "（[D] hold(win)/hold(loss)）" does not count)
  stumps       = parentheticals that still look grammatically broken (must be 0; see STUMP)

Usage: python strip_markers.py <draft.md> [--out <path>] [--dry-run]
       python strip_markers.py --all           # every drafts/*.md -> pandora/wallets/<proposed_filename>
       python strip_markers.py --audit         # --all, plus list every parenthetical the script rewrote
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).parent.parent
PANDORA = pathlib.Path("/Users/jim/projects/obsidian/pandora/wallets")
MARK = r"\[[A-E]\]"
TRACE_LINE = ("- 本報告全部數字來自 vault `reports/wallets-batch-2026-09b/data/<addr10>/analysis.txt`"
              "（分段 [A] 帳戶／[B] 機制／[C] 大波動日／[D] 持倉時間／[E] 資料極限，對應五題）；"
              "驗證用草稿（含逐數字出處標記）在同目錄 `drafts/`。")

# full-width parenthetical, ASCII () allowed inside (hold(win)/hold(loss)); and a plain ASCII one
PAREN_FW = re.compile(r"（(?:[^（）()]|\([^（）()]*\))*）")
PAREN_ASCII = re.compile(r"\((?:[^（）()])*\)")

# words that only ever point at analysis.txt — a segment made of these (plus ASCII field names,
# connectives and no digits) is a reference, not content
REF_WORDS = ("見", "出處", "來源", "依據", "參見", "引", "引用", "算式", "出自", "基於", "同", "含", "行", "各行", "段", "全段", "欄", "表",
             "列", "首列", "明細", "軌跡", "逐日軌跡", "分組", "分布", "說明", "對照表", "對手方表", "現有部位",
             "持倉快照", "進出場形態表", "進出場形態", "大日明細", "逐小時分布", "同一份", "那一行", "這行數字",
             "數字", "條目", "與", "的", "和", "及", "及其", "其", "自", "各", "各項", "各項數字",
             "取自", "皆取自", "均取自", "相減", "相加", "加總", "推算", "換算", "反推",
             "本報告推算", "本報告自算", "推導", "自算", "此為自算", "分別", "供交叉核對", "非", "原文")
REF_PATTERNS = [
    r"\d+\s*(?:worst|best|deepest|biggest)\s+[A-Za-z ]+(?:第\s*\d+\s*行)?",   # "10 worst episodes 第 7 行"
    r"\d+\s*大日(?:明細)?", r"\d+\s*biggest days", r"era\s*\d+", r"§\s*\d+(?:/\S*)?",
    r"第\s*\d+\s*(?:行|列)", r"[A-Za-z][A-Za-z0-9_/|.<>=+\-()]*",  # analysis.txt row pointers; ASCII field names incl. hold(win)
    # NOTE: "第 N 章／節／點" is deliberately NOT here — that is the report's own cross-reference, real content
]
_ref_pat = re.compile(r"^(?:" + "|".join(REF_PATTERNS) + r"|" + "|".join(map(re.escape, sorted(REF_WORDS, key=len, reverse=True)))
                      + r"|[\s，,、；;／/:：「」『』\"'*＋+\-—–…。.|\\$]+)+$")


def is_reference_segment(seg):
    s = seg.strip()
    if not s:
        return True
    if re.search(r"\d", s) and not re.fullmatch(r"\s*(?:" + "|".join(REF_PATTERNS[:5]) + r")\s*(?:[，,、]\s*(?:" + "|".join(REF_PATTERNS[:5]) + r"))*\s*", s):
        return False          # digits mean content, unless the whole segment is a numbered pointer
    return bool(_ref_pat.fullmatch(s))


def clean_inner(inner):
    """inner text of a parenthetical that contained a marker: drop markers, then reference-only segments"""
    inner = re.sub(r"(?:analysis\.txt\s*)?" + MARK + r"(?:\s*[／/＋+、,，]\s*" + MARK + r")*", " ", inner)
    segs = re.split(r"([，,；;、])", inner)          # keep delimiters
    kept, out = [], []
    for i in range(0, len(segs), 2):
        seg = segs[i]; delim = segs[i + 1] if i + 1 < len(segs) else ""
        if is_reference_segment(seg):
            continue
        kept.append((seg.strip(), delim))
    if not kept:
        return ""
    txt = ""
    for j, (seg, delim) in enumerate(kept):
        txt += seg + (delim if j < len(kept) - 1 else "")
    txt = re.sub(r"用\s+的\s*", "用", txt)
    txt = re.sub(r"\s*[，,、；;／/＋+]+\s*$", "", txt)
    txt = re.sub(r"^\s*[，,、；;／/＋+]+\s*", "", txt)
    txt = re.sub(r"[，,]\s*[，,、]", "、", txt)
    txt = re.sub(r"\s{2,}", " ", txt).strip()
    return txt


def strip_paren(m):
    s = m.group(0)
    if not re.search(MARK, s):
        return s
    inner = clean_inner(s[1:-1])
    return "" if not inner else s[0] + inner + s[-1]


def drop_source_column(text):
    out, block = [], []

    def flush():
        if not block:
            return
        cells = [c.strip() for c in block[0].strip().strip("|").split("|")]
        if cells and cells[-1] == "出處":
            for ln in block:
                parts = ln.rstrip("\n").rstrip().rstrip("|").split("|")
                is_sep = all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in parts[1:] if c.strip())
                prose = clean_inner(parts[-1]).strip() if not is_sep else ""
                if prose and prose != "出處":
                    parts[-2] = parts[-2].rstrip() + prose + " "
                out.append("|".join(parts[:-1]) + ("|" if is_sep else " |"))
        else:
            out.extend(l.rstrip("\n") for l in block)
        block.clear()

    for ln in text.splitlines():
        (block.append(ln) if ln.lstrip().startswith("|") else (flush(), out.append(ln)))
    flush()
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def strip_markers(text):
    text = drop_source_column(text)
    text = PAREN_FW.sub(strip_paren, text)
    text = PAREN_FW.sub(strip_paren, text)      # second pass: an outer paren whose inner （[E]） was just removed
    text = PAREN_ASCII.sub(strip_paren, text)
    # markers that sit in plain prose or a table cell (no parenthesis): drop with any trailing field name
    text = re.sub(r"\s*(?:analysis\.txt\s*)?" + MARK + r"(?:\s*[／/＋+]\s*" + MARK + r")*"
                  r"(?:\s*(?:現有部位|EQUITY BASIS|entry fills|era summary|position sizing|monthly cadence|"
                  r"top coins by[^，,。；;|）)]*|\d+ (?:worst|best) episodes))?", "", text)
    text = re.sub(MARK, "", text)
    # tidy
    text = re.sub(r"[ \t]+(?=[，。；、）])", "", text)
    text = re.sub(r"[（(]\s*(?:出處|來源|依據|參見|見|資料|source)\s*[:：]?\s*[）)]", "", text)
    text = re.sub(r"([（(])\s*(?:出處|來源|依據)\s*[:：]\s*(?=[^）)])", r"\1", text)
    text = re.sub(r"（\s*）|\(\s*\)", "", text)
    text = re.sub(r"，\s*）", "）", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?<=[一-鿿])[ \t]+(?=[一-鿿])", "", text)   # "與 該日" left where a marker sat
    text = re.sub(r"``\s*", "", text)                                          # "`[A]`" → "``" after marker removal
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^proposed_filename:.*\n", "", text, flags=re.M)
    return text


def add_trace(text):
    m = re.search(r"^## 相關\s*$", text, re.M)
    line = TRACE_LINE + "\n\n"
    if m:
        return text[:m.start()].rstrip("\n") + "\n" + line + text[m.start():]
    return text.rstrip("\n") + "\n\n" + line


def convert(src):
    return add_trace(strip_markers(src.read_text()))


# ---------------------------------------------------------------- guards
def _marker_free_parens(before):
    """parentheticals of the draft that carry no marker — nesting-aware"""
    blanked = PAREN_FW.sub(lambda m: " " * len(m.group(0)) if re.search(MARK, m.group(0)) else m.group(0), before)
    return [m.group(0) for m in PAREN_FW.finditer(blanked)] + \
           [m.group(0) for m in PAREN_ASCII.finditer(blanked) if not re.search(MARK, m.group(0))]


def lost_parentheticals(before, after):
    norm = lambda s: re.sub(r"\s+", "", s)          # whitespace inside a paren may legitimately be tidied
    a = norm(after)
    return [k for k in _marker_free_parens(before) if norm(k) not in a]


STUMP = re.compile(
    r"[（(]\s*[，,、；;／/]"                                      # opens with punctuation ("(+4,058)" is a signed number, not a stump)
    r"|[，,、；;]\s*[＋+／/]?\s*[）)]"                             # closes with a comma-class char, optionally + or /
    r"|[，,]\s*[，,、]"                                           # doubled punctuation
    r"|(?:^|[（(，,、；;\s])(?:見|來源|引|出自|基於|算式)\s*[）)]"   # reference verb left hanging right before the close paren
    r"|用\s+的|非\s+條目|/\s*的\s|``"
)


def stumps(text):
    body = re.sub(r"^- 本報告全部數字來自.*$", "", text, flags=re.M)
    return [ln.strip()[:140] for ln in body.splitlines() if STUMP.search(ln)]


def residual(text):
    body = re.sub(r"^- 本報告全部數字來自.*$", "", text, flags=re.M)
    return [ln for ln in body.splitlines() if re.search(MARK, ln)]


def rewritten(before, after):
    src = {m.group(0) for m in PAREN_FW.finditer(before)} | {m.group(0) for m in PAREN_ASCII.finditer(before)}
    outs = [m.group(0) for m in PAREN_FW.finditer(after)] + [m.group(0) for m in PAREN_ASCII.finditer(after)]
    return [p for p in outs if p not in src and "分段" not in p and "含逐數字出處標記" not in p]


def main(argv):
    if argv[:1] in (["--all"], ["--audit"]):
        bad = 0
        for d in sorted((ROOT / "drafts").glob("*.md")):
            before = d.read_text()
            fn = re.search(r'^proposed_filename:\s*"?([^"\n]+)"?', before, re.M).group(1).strip()
            out = convert(d)
            (PANDORA / fn).write_text(out)
            r, lost, st = residual(out), lost_parentheticals(before, out), stumps(out)
            flag = "" if not (r or lost or st) else "   <-- CHECK"
            print(f"{d.name} -> {fn}  residual={len(r)} lost_parens={len(lost)} stumps={len(st)}{flag}")
            for ln in r[:3]:
                print("      residual:", ln[:120])
            for k in lost[:5]:
                print("      LOST:", k[:120])
            for k in st[:8]:
                print("      STUMP:", k)
            if argv == ["--audit"]:
                for p in rewritten(before, out):
                    print("      rewritten:", p[:110])
            bad += bool(r or lost or st)
        print(f"written {len(list((ROOT / 'drafts').glob('*.md')))}, files needing attention: {bad}")
        return
    src = pathlib.Path(argv[0])
    out = convert(src)
    if "--dry-run" in argv:
        sys.stdout.write(out)
    else:
        dst = pathlib.Path(argv[argv.index("--out") + 1]) if "--out" in argv else src.with_suffix(".clean.md")
        dst.write_text(out); print("wrote", dst)


if __name__ == "__main__":
    main(sys.argv[1:])
