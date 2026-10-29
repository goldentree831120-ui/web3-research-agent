"""A JSON-RPC client that can only READ.

Guardrail: there is no private key anywhere in this project, and on top of that the client
refuses every method not on an explicit allowlist. eth_sendRawTransaction, eth_sendTransaction,
eth_sign etc. are rejected before any network call, even if a bug or a prompt injection tried.
"""
import itertools

import requests

ALLOWED_METHODS = frozenset({"eth_call", "eth_chainId", "eth_blockNumber", "eth_getBalance", "eth_getBlockByNumber"})
SEPOLIA_CHAIN_ID = 11155111


class RpcError(RuntimeError):
    pass


class ReadOnlyRpc:
    def __init__(self, url: str, timeout: float = 15, expected_chain_id: int = SEPOLIA_CHAIN_ID, session=None):
        self.url = url
        self.timeout = timeout
        self.expected_chain_id = expected_chain_id
        self._ids = itertools.count(1)
        self._session = session or requests.Session()
        self._checked_chain = False

    def call(self, method: str, params: list):
        if method not in ALLOWED_METHODS:
            raise PermissionError(f"RPC method {method!r} is not allowed: this agent is read-only")
        if not self._checked_chain and method != "eth_chainId":
            self._check_chain()
        r = self._session.post(self.url, json={"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params},
                               timeout=self.timeout)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RpcError(body["error"].get("message", str(body["error"])))
        return body["result"]

    def _check_chain(self):
        cid = int(self.call("eth_chainId", []), 16)
        if cid != self.expected_chain_id:
            raise RpcError(f"RPC is on chain {cid}, expected {self.expected_chain_id} (Sepolia)")
        self._checked_chain = True

    def eth_call(self, to: str, data: str) -> str:
        return self.call("eth_call", [{"to": to, "data": data}, "latest"])
