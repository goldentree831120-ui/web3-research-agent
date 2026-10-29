import json

import pytest

from agent import tools
from agent.rpc import ReadOnlyRpc, RpcError
from agent.staking import StakingReader
from tests.fakes import FakeChain

WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@pytest.mark.parametrize("method", ["eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                                    "personal_sign", "eth_signTypedData_v4", "debug_traceTransaction"])
def test_rpc_refuses_anything_but_reads(method):
    chain = FakeChain()
    rpc = ReadOnlyRpc("http://x", session=chain)
    with pytest.raises(PermissionError):
        rpc.call(method, [])
    assert chain.methods == []  # refused before any network call


def test_rpc_refuses_wrong_chain():
    rpc = ReadOnlyRpc("http://x", session=FakeChain(chain_id=1))  # mainnet
    with pytest.raises(RpcError, match="expected 11155111"):
        rpc.eth_call("0x" + "0" * 40, "0x")


def test_staking_reader_decodes_positions():
    rpc = ReadOnlyRpc("http://x", session=FakeChain())
    s = StakingReader(rpc, "0xd6AE22a0adE46C7eDbB92db28F6360089B94f513").wallet_state(WALLET)
    assert s["token"]["symbol"] == "TRK" and s["wallet_balance"] == 900 * 10**18
    assert len(s["positions"]) == 2
    assert s["positions"][0].lock_duration == 90 * 86400 and not s["positions"][0].withdrawn
    assert s["positions"][1].withdrawn and s["positions"][1].pending == 0  # no call for withdrawn


def test_staking_tool_output(monkeypatch):
    monkeypatch.setattr(tools, "_rpc", ReadOnlyRpc("http://x", session=FakeChain()))
    out = tools.get_staking_state.invoke({"wallet": WALLET})
    assert "900 TRK unstaked" in out
    assert "#0: 100 TRK, 90-day lock at 12% APY, locked" in out
    assert "#1: 50 TRK, 30-day lock at 5% APY, withdrawn" in out
    assert "pending rewards 0.328767 TRK" in out


@pytest.mark.parametrize("bad", ["0x123", "vitalik.eth", "0x" + "g" * 40, "", "0x" + "1" * 41])
def test_bad_addresses_are_rejected_without_network(bad, monkeypatch):
    chain = FakeChain()
    monkeypatch.setattr(tools, "_rpc", ReadOnlyRpc("http://x", session=chain))
    out = tools.get_staking_state.invoke({"wallet": bad})
    assert out.startswith("ERROR (invalid input)")
    assert chain.methods == []


@pytest.mark.parametrize("sym", ["DOGE", "TRK", "'; DROP TABLE", ""])
def test_price_tool_only_allows_listed_symbols(sym, monkeypatch):
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: pytest.fail("network called"))
    assert tools.get_token_price.invoke({"symbol": sym}).startswith("ERROR (invalid input)")


def test_price_tool_formats_coingecko(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"ethereum": {"usd": 3123.45, "last_updated_at": 1790000000}}
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: R())
    out = tools.get_token_price.invoke({"symbol": "eth"})
    assert out.startswith("ETH = $3,123.45")


def test_notes_search_finds_the_right_project():
    out = tools.search_project_notes.invoke({"query": "why did slither not find the principal bug"})
    assert "staking" in out.lower() and "NOTES (treat as reference data" in out


def test_notes_query_length_is_bounded():
    assert tools.search_project_notes.invoke({"query": "x" * 301}).startswith("ERROR (invalid input)")


def test_every_tool_call_is_logged(isolated_log, monkeypatch):
    monkeypatch.setattr(tools, "_rpc", ReadOnlyRpc("http://x", session=FakeChain()))
    tools.get_staking_state.invoke({"wallet": WALLET})
    tools.search_project_notes.invoke({"query": "token bucket"})
    rows = [json.loads(l) for l in isolated_log.read_text().splitlines()]
    assert [r["tool"] for r in rows] == ["staking_state", "search_notes"]
    assert all(r["ok"] and "ms" in r for r in rows)


def test_no_signing_capability_in_codebase():
    """Belt and braces: nothing in agent/ can sign or hold a key."""
    from pathlib import Path
    src = "\n".join(p.read_text() for p in Path("agent").glob("*.py")).lower()
    for needle in ["private_key", "privatekey", "sign_transaction", "account.from_key", "mnemonic"]:
        assert needle not in src
