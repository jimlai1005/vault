"""Public (unauthenticated) endpoints, typed and routed through the boundary."""
from __future__ import annotations

from compound.bfx import models
from compound.bfx.boundary import CallSpec, call


class PublicClient:
    def __init__(self, transport):
        self._t = transport

    def get_ticker(self, symbol="fUSD"):
        models.require_funding_symbol(symbol)
        spec = CallSpec("ticker/%s" % symbol, kind="read", idempotent=True)
        payload = call(spec, self._t.public_get, "ticker/%s" % symbol)
        return models.FundingTicker.from_array(payload)

    def get_book(self, symbol="fUSD", precision="P0", length=100):
        models.require_funding_symbol(symbol)
        spec = CallSpec("book/%s" % symbol, kind="read", idempotent=True)
        payload = call(spec, self._t.public_get,
                       "book/%s/%s" % (symbol, precision),
                       params={"len": length})
        return [models.BookEntry.from_array(row) for row in payload]

    def get_candles(self, key, start=None, end=None, limit=None, sort=-1):
        """key e.g. 'trade:1h:fUSD:a30:p2:p30' (api ref §3.3)."""
        params = {"sort": sort}
        if start is not None:
            params["start"] = int(start)
        if end is not None:
            params["end"] = int(end)
        if limit is not None:
            params["limit"] = int(limit)
        spec = CallSpec("candles/%s" % key, kind="read", idempotent=True)
        payload = call(spec, self._t.public_get,
                       "candles/%s/hist" % key, params=params)
        return [models.Candle.from_array(row) for row in payload]

    def get_trades(self, symbol="fUSD", limit=120):
        models.require_funding_symbol(symbol)
        spec = CallSpec("trades/%s" % symbol, kind="read", idempotent=True)
        payload = call(spec, self._t.public_get,
                       "trades/%s/hist" % symbol, params={"limit": limit})
        return [models.FundingTrade.from_array(row) for row in payload]

    def get_funding_stats(self, symbol="fUSD", limit=120):
        models.require_funding_symbol(symbol)
        spec = CallSpec("funding/stats/%s" % symbol, kind="read", idempotent=True)
        payload = call(spec, self._t.public_get,
                       "funding/stats/%s/hist" % symbol, params={"limit": limit})
        return [models.FundingStat.from_array(row) for row in payload]
