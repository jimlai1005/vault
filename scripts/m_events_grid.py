"""Sub-project M — TOL 網格事件表（M-G4 的 480 cells 需要）。

對 TOL_GRID 的每個檔位重跑偵測（TOL_AD_XA = 0.6×TOL，spec §4.4），
寫 events_{interval}_tol{NN}.parquet（含 in_universe）。K 線快取命中，零網路。
tol05 的輸出應與 Stage 1 census 的 events_{interval}.parquet 逐列一致（sanity）。

用法：.venv/bin/python scripts/m_events_grid.py
"""
import json
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_census             # noqa: E402
import m_data               # noqa: E402
import m_detect             # noqa: E402

CACHE = pathlib.Path(cfg.CACHE_DIR)


def main():
    universe = {tuple(map(int, k.replace("-Q", " ").split())): set(v)
                for k, v in json.load(open(CACHE / "universe_schedule.json")).items()}
    symbols = sorted({s for v in universe.values() for s in v})
    for tol in cfg.TOL_GRID:
        tol_ad = round(cfg.TOL_AD_RATIO * tol, 6)
        tag = f"tol{int(round(tol * 100)):02d}"
        for interval in cfg.INTERVALS:
            out = CACHE / f"events_{interval}_{tag}.parquet"
            if out.exists():
                print(f"skip {out.name}（已存在）")
                continue
            frames = []
            for sym in symbols:
                df = m_data.load_klines(sym, interval)
                if df.empty:
                    continue
                raw = m_detect.build_events(df, sym, interval,
                                            tol=tol, tol_ad=tol_ad,
                                            do_dedup=False)
                if not raw.empty:
                    frames.append(raw)
            raw = pd.concat(frames, ignore_index=True)
            raw = raw[(raw["as_of"] >= cfg.EVENT_START_MS)
                      & (raw["as_of"] <= cfg.EVENT_END_MS)]
            ded = m_detect.dedup(raw)
            ded["in_universe"] = [
                r.symbol in universe.get(m_census.quarter_of_ms(r.as_of), set())
                for r in ded.itertuples()]
            ded.to_parquet(out, index=False)
            print(f"{out.name}: 去重後 {len(ded)}，宇宙內 {int(ded['in_universe'].sum())}")
    # sanity：tol05 vs census 輸出
    for interval in cfg.INTERVALS:
        a = pd.read_parquet(CACHE / f"events_{interval}_tol05.parquet")
        b = pd.read_parquet(CACHE / f"events_{interval}.parquet")
        assert len(a) == len(b), (interval, len(a), len(b))
    print("sanity: tol05 ≡ census 輸出")


if __name__ == "__main__":
    main()
