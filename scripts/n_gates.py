"""Sub-project N — 十道 gate 的判定表。spec §8.1。

【機械導出，無裁量】。任何需要「判斷一下」的地方都是設計錯誤——
若判定表無法涵蓋某個結果組合，停下來修 spec，不要在此加特例。
"""
GATE_KEYS = ("G0", "G1", "G1b", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def verdict(g):
    """spec §8.1 判定表。缺任何一把鑰匙 -> KeyError（不得靜默預設 True）。"""
    v = {k: bool(g[k]) for k in GATE_KEYS}
    if not (v["G0"] and v["G1"]):
        return "作廢"
    if not v["G1b"]:
        return "作廢"
    if not v["G2"]:
        return "NO-GO"
    if not v["G3"]:
        return "NO-GO"
    if not (v["G4"] and v["G5"] and v["G6"] and v["G7"]):
        return "NO-GO"
    return "GO" if v["G8"] else "GO（機制未獲支持）"
