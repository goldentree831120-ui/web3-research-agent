"""Fakes so the agent loop and the tools can be tested without an LLM key or network."""
from typing import Any

from eth_abi import encode
from eth_utils import function_signature_to_4byte_selector
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedModel(BaseChatModel):
    """Returns pre-written AIMessages in order (repeating the last one), and accepts bind_tools."""
    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        msg = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name, args, i="1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}])


def final(answer="ok", sources=(), confidence="high", refused=False, i="9"):
    return tool_call("answer", {"answer": answer, "sources": list(sources), "confidence": confidence, "refused": refused}, i)


def sel(sig):
    return "0x" + function_signature_to_4byte_selector(sig).hex()


class FakeChain:
    """Answers eth_* calls like a Sepolia node holding one TRK staking contract."""
    TOKEN = "0x2ffEC8C4Db1931b33985c26a8abFB0890C10e4a5"
    NOW = 1_790_000_000

    def __init__(self, positions=None, chain_id=11155111):
        self.chain_id = chain_id
        self.positions = positions if positions is not None else [
            (100 * 10**18, self.NOW - 10 * 86400, 90 * 86400, 1200, self.NOW - 10 * 86400, False),
            (50 * 10**18, self.NOW - 400 * 86400, 30 * 86400, 500, self.NOW - 400 * 86400, True),
        ]
        self.methods = []

    def post(self, url, json, timeout):
        self.methods.append(json["method"])
        return _Resp({"jsonrpc": "2.0", "id": json["id"], "result": self._answer(json["method"], json["params"])})

    def _answer(self, method, params):
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getBlockByNumber":
            return {"number": hex(12345), "timestamp": hex(self.NOW)}
        data = params[0]["data"]
        s = data[:10]
        out = {
            sel("stakingToken()"): lambda: encode(["address"], [self.TOKEN]),
            sel("symbol()"): lambda: encode(["string"], ["TRK"]),
            sel("decimals()"): lambda: encode(["uint8"], [18]),
            sel("balanceOf(address)"): lambda: encode(["uint256"], [900 * 10**18]),
            sel("positionsOf(address)"): lambda: encode(["(uint256,uint256,uint256,uint256,uint256,bool)[]"], [self.positions]),
            sel("pendingRewards(address,uint256)"): lambda: encode(["uint256"], [328767123287671232]),
        }[s]()
        return "0x" + out.hex()


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body
