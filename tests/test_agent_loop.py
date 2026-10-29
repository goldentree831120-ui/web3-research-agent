from agent import tools
from agent.agent import ask, build_agent
from agent.rpc import ReadOnlyRpc
from tests.fakes import FakeChain, ScriptedModel, final, tool_call

WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def test_tool_then_structured_answer(monkeypatch):
    monkeypatch.setattr(tools, "_rpc", ReadOnlyRpc("http://x", session=FakeChain()))
    model = ScriptedModel(script=[tool_call("get_staking_state", {"wallet": WALLET}),
                                  final("You have 100 TRK staked.", ["get_staking_state"])])
    r = ask("How much do I have staked?", agent=build_agent(model))
    assert [c["name"] for c in r["tool_calls"]] == ["get_staking_state", "answer"]
    assert r["answer"]["answer"] == "You have 100 TRK staked."
    assert not r["hit_limit"]


def test_refusal_path_calls_no_data_tools():
    model = ScriptedModel(script=[final("I can't send transactions; I'm read-only.", refused=True)])
    r = ask("Withdraw my position 0 now", agent=build_agent(model))
    assert r["answer"]["refused"] is True
    assert [c["name"] for c in r["tool_calls"]] == ["answer"]


def test_tool_error_reaches_the_model_instead_of_crashing():
    model = ScriptedModel(script=[tool_call("get_token_price", {"symbol": "TRK"}),
                                  final("TRK has no market price.", confidence="high")])
    r = ask("Price of TRK?", agent=build_agent(model))
    assert any("unsupported symbol" in e for e in r["tool_errors"])
    assert r["answer"]["answer"] == "TRK has no market price."


def test_runaway_model_is_stopped_by_limits(monkeypatch):
    monkeypatch.setattr(tools, "_rpc", ReadOnlyRpc("http://x", session=FakeChain()))
    looping = ScriptedModel(script=[tool_call("search_project_notes", {"query": "again"}, i=str(n)) for n in range(50)])
    r = ask("loop forever", agent=build_agent(looping))
    assert r["hit_limit"] is True
    assert len(r["tool_calls"]) <= 8  # capped by MAX_TOOL_CALLS / MAX_MODEL_CALLS


def test_tokens_are_summed_from_provider_usage():
    # The eval's token budget relies on this: every model call's reported usage is counted.
    def with_usage(msg, total):
        return msg.model_copy(update={"usage_metadata": {"input_tokens": total - 10, "output_tokens": 10,
                                                         "total_tokens": total}})
    model = ScriptedModel(script=[with_usage(tool_call("search_project_notes", {"query": "slither"}), 900),
                                  with_usage(final("accounting bug"), 1300)])
    r = ask("Why didn't Slither catch it?", agent=build_agent(model))
    assert r["tokens"] == 2200 and r["model_calls"] == 2
