"""Sub-project M — 形態普查（Stage 1 交付物）。

輸出各形態的事件數（去重前後）、空交集無關（偵測層已內建）、多形態 XABC 率，
逐 interval 分列。這些數字是 Stage 2 回測層的設計輸入，也是 spec §4.2 要求的
強制揭露之一。

用法：.venv/bin/python scripts/m_census.py
"""
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_data               # noqa: E402
import m_detect             # noqa: E402

OUT = pathlib.Path("reports/m-pattern-census.md")


def census():
    candidates = m_data.binance_universe_symbols()
    print(f"候選池（現存 USDT 永續）: {len(candidates)} 個 symbol")
    universe = m_data.build_pit_universe_m(candidates)
    symbols = sorted({s for syms in universe.values() for s in syms})
    n_q = sum(1 for v in universe.values() if v)
    print(f"PIT 宇宙: {n_q} 個季度有幣單，聯集 {len(symbols)} 個 symbol")

    lines = ["# Sub-project M — 形態普查（Stage 1）", "",
             f"> 產出：2026-08-07｜spec v3.2｜偵測參數全凍結於 scripts/m_config.py",
             "",
             f"- 候選池：{len(candidates)} 個現存 Binance USDT 永續（**已下市幣不在"
             f" exchangeInfo 中——候選池層級的殘餘倖存者偏誤，spec §10 限制 3**）",
             f"- PIT 季度輪換（{cfg.UNIVERSE_FIRST_QUARTER}~{cfg.UNIVERSE_LAST_QUARTER}"
             f"，門檻 ${cfg.UNIVERSE_MIN_QUOTE_VOL/1e6:.0f}M/90d 中位、上市"
             f"≥{cfg.UNIVERSE_MIN_LISTED_DAYS}d、每季 top {cfg.UNIVERSE_TOP_N}）"
             f"：聯集 {len(symbols)} 個 symbol",
             f"- pivot 尺度 {cfg.PIVOT_LENGTHS}｜TOL={cfg.TOL}/TOL_AD_XA={cfg.TOL_AD_XA}"
             f"｜事件窗 2020-07-01 ~ 2026-06-30（as_of 基準）", ""]

    per_q = sorted(((y, q), len(v)) for (y, q), v in universe.items())
    lines += ["## PIT 宇宙逐季幣數", "",
              "| 季度 | 幣數 |", "|---|---|"]
    lines += [f"| {y}-Q{q} | {n} |" for (y, q), n in per_q]
    lines.append("")

    for interval in cfg.INTERVALS:
        frames = []
        for k, sym in enumerate(symbols):
            df = m_data.load_klines(sym, interval)
            if df.empty:
                continue
            raw = m_detect.build_events(df, sym, interval, do_dedup=False)
            if not raw.empty:
                frames.append(raw)
            if (k + 1) % 10 == 0:
                print(f"  {interval}: {k+1}/{len(symbols)} 完成")
        if not frames:
            lines += [f"## {interval}", "", "無事件。", ""]
            continue
        raw = pd.concat(frames, ignore_index=True)
        raw = raw[(raw["as_of"] >= cfg.EVENT_START_MS)
                  & (raw["as_of"] <= cfg.EVENT_END_MS)]
        ded = m_detect.dedup(raw)
        multi = (ded.groupby("xabc_group_id")["pattern"].nunique() > 1)
        lines += [f"## {interval}", "",
                  f"去重前 {len(raw)}｜去重後 {len(ded)}｜"
                  f"多形態 XABC 佔比 {multi.mean():.1%}", "",
                  "| 形態 | 去重前 | 去重後 | IS | OOS |", "|---|---|---|---|---|"]
        for p in cfg.PATTERNS:
            sub = ded[ded["pattern"] == p]
            n_is = int((sub["as_of"] <= cfg.IS_END_MS).sum())
            lines.append(f"| {p} | {int((raw['pattern'] == p).sum())} | "
                         f"{len(sub)} | {n_is} | {len(sub) - n_is} |")
        lines.append("")
        ded.to_parquet(f"data/cache/harmonic_m/events_{interval}.parquet", index=False)
        print(f"  {interval}: 去重後 {len(ded)} 事件 → events_{interval}.parquet")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    census()
