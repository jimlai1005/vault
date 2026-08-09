"""Sub-project N — 訂單流確認特徵。spec §5。

【全部無自由參數】——ABS 只取 D_sweep 的符號、DIV 只做兩個 CVD 值的比較。
幅度門檻會推高試驗數且（依 M 的教訓）買到的是勝率不是期望值，故一律不設。
|D_sweep| 與 D_sweep/V_sweep 的分布只落檔揭露。

缺值一律判否（P13），兩臂同規則。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_orderflow as of  # noqa: E402

ARM_REQUIRES = {
    "sweep_only": (),
    "sweep+ABS": ("abs_ok",),
    "sweep+ABSs": ("abs_strict_ok",),
    "sweep+DIV": ("div_ok",),
    "sweep+ABS+DIV": ("abs_ok", "div_ok"),
    "sweep+ABSs+DIV": ("abs_strict_ok", "div_ok"),
}


def abs_ok(d_sweep, direction):
    """spec §5.2：掃單腿的主動流方向與交易方向【相反】＝被吸收。

    空方掃單（direction=-1，做空）：池上方是主動【買】被吸收 → D_sweep > 0
    多方掃單（direction=+1，做多）：池下方是主動【賣】被吸收 → D_sweep < 0
    """
    d = float(d_sweep)
    if not np.isfinite(d):
        return False
    return bool(d > 0 if direction == -1 else d < 0)


def div_ok(cvd_j, cvd_pool, direction):
    """spec §5.3：價格創了比池更極端的值，但累積 delta 沒有同步跟上。

    空方掃單：CVD_j <= CVD_pool（價更高但買盤沒更強）
    多方掃單：CVD_j >= CVD_pool
    """
    a, b = float(cvd_j), float(cvd_pool)
    if not (np.isfinite(a) and np.isfinite(b)):
        return False
    return bool(a <= b if direction == -1 else a >= b)


def abs_strict_ok(d_sweep, bar_delta, direction):
    """spec §5.2.1（修訂 A3）：完整的吸收語意，仍然無自由參數。

    池上方在【主動買】把價格推上去，但【整根棒】的淨流是賣
    -> 有大量靜止賣單在吸收那些主動買單。
      空方掃單：D_sweep > 0 且 D_bar < 0
      多方掃單：D_sweep < 0 且 D_bar > 0

    原 ABS 只看 D_sweep 的符號，而該符號幾乎被「掃單發生了」蘊含
    （pilot 覆蓋率 96.5%），故鑑別力不足。本函式的 pilot 覆蓋率 10.4%。
    """
    if not abs_ok(d_sweep, direction):
        return False
    b = float(bar_delta)
    if not np.isfinite(b):
        return False
    return bool(b < 0 if direction == -1 else b > 0)


def arm_pass(arm, flags):
    """該臂要求的旗標是否全部成立。未知臂別 -> KeyError（不得靜默放行）。"""
    req = ARM_REQUIRES[arm]
    return all(bool(flags[k]) for k in req) if req else True


def bar_value_at(bars_of, t, col):
    """逐棒訂單流表在時點 t 的某欄；查無該棒 -> NaN。"""
    m = bars_of["t"].to_numpy() == int(t)
    if not m.any():
        return float("nan")
    return float(bars_of[col].to_numpy()[m][0])


def cvd_at(bars_of, t):
    """逐棒訂單流表在時點 t 的 CVD；查無該棒 -> NaN。"""
    m = bars_of["t"].to_numpy() == int(t)
    if not m.any():
        return float("nan")
    return float(bars_of["cvd"].to_numpy()[m][0])


def attach(events, bars_of, trades_by_day, bar_ms):
    """事件表 → 加上 d_sweep / v_sweep / cvd_j / cvd_pool / abs_ok / div_ok。

    trades_by_day：dict(day 'YYYY-MM-DD' -> (trades_df, index))，
    由呼叫端依事件涉及的日期預先載入（避免重複讀檔）。
    缺資料的事件 -> d_sweep = NaN，下游記 nodata（P13）。
    """
    out = events.copy()
    ds, vs = [], []
    for e in out.to_dict("records"):
        day = pd.Timestamp(int(e["t_j"]), unit="ms", tz="UTC").strftime("%Y-%m-%d")
        pair = trades_by_day.get(day)
        if pair is None:
            ds.append(float("nan"))
            vs.append(float("nan"))
            continue
        tr, idx = pair
        d, v = of.sweep_delta(tr, idx, int(e["t_j"]), float(e["pool"]),
                              int(e["direction"]))
        ds.append(d)
        vs.append(v)
    out["d_sweep"] = ds
    out["v_sweep"] = vs
    out["cvd_j"] = [cvd_at(bars_of, t) for t in out["t_j"]]
    out["cvd_pool"] = [cvd_at(bars_of, t) for t in out["pool_t"]]
    out["bar_delta"] = [bar_value_at(bars_of, t, "delta") for t in out["t_j"]]
    out["abs_ok"] = [abs_ok(d, s) for d, s in zip(out["d_sweep"], out["direction"])]
    out["abs_strict_ok"] = [abs_strict_ok(d, b, s) for d, b, s
                            in zip(out["d_sweep"], out["bar_delta"], out["direction"])]
    out["div_ok"] = [div_ok(a, b, s) for a, b, s
                     in zip(out["cvd_j"], out["cvd_pool"], out["direction"])]
    return out
