from hlvault.universe import top_addresses


def test_top_addresses_ranks_and_truncates():
    rows = [
        {
            "ethAddress": f"0x{i:040x}",
            "windowPerformances": [["month", {"pnl": str(i)}]],
        }
        for i in range(5)
    ]
    out = top_addresses(rows, n=3)
    assert len(out) == 3
    assert out[0] == "0x" + f"{4:040x}"
