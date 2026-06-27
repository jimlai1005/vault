from __future__ import annotations

import pandas as pd

Address = str  # 42-char hex, validated at the IO boundary
ReturnSeries = pd.Series  # DatetimeIndex -> daily return float
