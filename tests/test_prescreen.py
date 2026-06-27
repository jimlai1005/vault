from hlvault.prescreen import prescreen


def _row(addr, acct, vlm, roi):
    return {
        "ethAddress": addr,
        "accountValue": str(acct),
        "windowPerformances": [
            ["month", {"pnl": "1", "roi": "0.1", "vlm": str(vlm)}],
            ["allTime", {"pnl": "1", "roi": str(roi), "vlm": str(vlm)}],
        ],
    }


def test_prescreen_drops_vaults_dust_and_ranks():
    rows = [
        _row("0xgood1", acct=5_000_000, vlm=10_000_000, roi=2.0),
        _row("0xgood2", acct=2_000_000, vlm=5_000_000, roi=1.0),
        _row("0xvault", acct=900_000_000, vlm=99_000_000, roi=5.0),   # vault-scale
        _row("0xdust", acct=1000, vlm=100, roi=3.0),                  # low volume
        _row("0xloser", acct=1_000_000, vlm=5_000_000, roi=-0.5),     # negative ROI
    ]
    out = prescreen(rows, keep=10)
    assert "0xvault" not in out
    assert "0xdust" not in out
    assert "0xloser" not in out
    assert out == ["0xgood1", "0xgood2"]   # ranked by allTime ROI desc


def test_prescreen_truncates_to_keep():
    rows = [_row(f"0x{i}", 1_000_000, 5_000_000, float(i)) for i in range(20)]
    out = prescreen(rows, keep=5)
    assert len(out) == 5
