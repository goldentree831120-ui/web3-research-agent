"""Read the Sepolia staking contract (Staking.sol) with raw eth_call + ABI decoding."""
from dataclasses import dataclass

from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector, to_checksum_address

from .rpc import ReadOnlyRpc

YEAR = 365 * 86400


def _sel(sig: str) -> str:
    return "0x" + function_signature_to_4byte_selector(sig).hex()


@dataclass
class Position:
    id: int
    amount: int
    start_time: int
    lock_duration: int
    reward_rate_bps: int
    last_claim_time: int
    withdrawn: bool
    pending: int

    @property
    def unlock_time(self) -> int:
        return self.start_time + self.lock_duration


class StakingReader:
    def __init__(self, rpc: ReadOnlyRpc, staking_address: str):
        self.rpc = rpc
        self.staking = to_checksum_address(staking_address)
        self._token = None

    def _call(self, to: str, sig: str, types_in: list, args: list, types_out: list):
        data = _sel(sig) + encode(types_in, args).hex()
        raw = self.rpc.eth_call(to, data)
        return decode(types_out, bytes.fromhex(raw[2:]))

    def token(self) -> dict:
        if self._token is None:
            (addr,) = self._call(self.staking, "stakingToken()", [], [], ["address"])
            addr = to_checksum_address(addr)
            (symbol,) = self._call(addr, "symbol()", [], [], ["string"])
            (decimals,) = self._call(addr, "decimals()", [], [], ["uint8"])
            self._token = {"address": addr, "symbol": symbol, "decimals": decimals}
        return self._token

    def wallet_state(self, wallet: str) -> dict:
        wallet = to_checksum_address(wallet)
        tok = self.token()
        (balance,) = self._call(tok["address"], "balanceOf(address)", ["address"], [wallet], ["uint256"])
        (raw_positions,) = self._call(self.staking, "positionsOf(address)", ["address"], [wallet],
                                      ["(uint256,uint256,uint256,uint256,uint256,bool)[]"])
        positions = []
        for i, p in enumerate(raw_positions):
            pending = 0
            if not p[5]:
                (pending,) = self._call(self.staking, "pendingRewards(address,uint256)", ["address", "uint256"],
                                        [wallet, i], ["uint256"])
            positions.append(Position(i, p[0], p[1], p[2], p[3], p[4], p[5], pending))
        block = self.rpc.call("eth_getBlockByNumber", ["latest", False])
        return {"wallet": wallet, "token": tok, "wallet_balance": balance, "positions": positions,
                "block_number": int(block["number"], 16), "block_timestamp": int(block["timestamp"], 16)}
