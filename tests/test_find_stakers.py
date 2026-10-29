"""find_stakers: falls back to another endpoint when one has pruned its logs, and shrinks the
block range when an endpoint limits it."""
import eval.find_stakers as fs


def fake_rpc(behaviour):
    calls = []

    def rpc(url, method, params):
        calls.append((url, method, params))
        if method == "eth_chainId":
            return hex(11155111)
        return behaviour(url, params[0])
    return rpc, calls


def test_pruned_endpoint_falls_back_to_the_next(monkeypatch):
    def behaviour(url, q):
        if url == "a":
            raise RuntimeError("pruned history unavailable")
        return [{"topics": ["t", "0x" + "0" * 24 + "ab" * 20]}]
    rpc, calls = fake_rpc(behaviour)
    monkeypatch.setattr(fs, "rpc", rpc)
    logs = fs.staked_logs(["a", "b"], 100, 150, 10_000)
    assert len(logs) == 1
    assert sum(1 for u, m, _ in calls if u == "a" and m == "eth_getLogs") == 1  # no pointless halving


def test_range_limit_shrinks_windows_and_covers_every_block(monkeypatch):
    def behaviour(url, q):
        lo, hi = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        if hi - lo + 1 > 2500:
            raise RuntimeError("block range too large")
        return [{"topics": ["t", "0x" + "0" * 24 + "cd" * 20], "blockNumber": hex(lo)}]
    rpc, calls = fake_rpc(behaviour)
    monkeypatch.setattr(fs, "rpc", rpc)
    fs.staked_logs(["a"], 1000, 10_999, 10_000)
    ok = [(int(p[0]["fromBlock"], 16), int(p[0]["toBlock"], 16)) for u, m, p in calls
          if m == "eth_getLogs" and int(p[0]["toBlock"], 16) - int(p[0]["fromBlock"], 16) + 1 <= 2500]
    assert ok[0][0] == 1000 and ok[-1][1] == 10_999
    assert all(b[0] == a[1] + 1 for a, b in zip(ok, ok[1:]))  # contiguous, no gaps
