#!/usr/bin/env python3
"""List wallets that have staked in the current Sepolia staking contract, to pick EVAL_WALLET.

    python -m eval.find_stakers

Reads `Staked` events with eth_getLogs (public data, no key), then each wallet's open positions
through the agent's own read-only reader. This is a setup helper, not part of the agent: the
agent's RPC client still only allows its 5 read methods. Prints public addresses only.
"""
import argparse
from collections import Counter

import requests
from eth_utils import keccak, to_checksum_address

from agent.config import CONFIG
from agent.rpc import SEPOLIA_CHAIN_ID, ReadOnlyRpc
from agent.staking import StakingReader

STAKED_TOPIC = "0x" + keccak(text="Staked(address,uint256,uint256,uint256)").hex()
DEPLOY_BLOCK = 11_962_251  # from defi-portfolio-tracker's README


def rpc(method: str, params: list):
    assert method in {"eth_chainId", "eth_blockNumber", "eth_getLogs"}  # reads only
    r = requests.post(CONFIG.sepolia_rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=CONFIG.http_timeout)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body["result"]


def staked_logs(start: int, end: int, step: int) -> list:
    logs, lo = [], start
    while lo <= end:
        hi = min(lo + step - 1, end)
        try:
            logs += rpc("eth_getLogs", [{"address": CONFIG.staking_address, "topics": [STAKED_TOPIC],
                                         "fromBlock": hex(lo), "toBlock": hex(hi)}])
            lo = hi + 1
        except (RuntimeError, requests.RequestException) as e:
            if step <= 500:
                raise
            step //= 2  # the endpoint limits the block range; try smaller windows
            print(f"  (range too large: {e}; retrying with {step}-block windows)")
    return logs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-block", type=int, default=DEPLOY_BLOCK)
    ap.add_argument("--step", type=int, default=10_000)
    a = ap.parse_args()

    if int(rpc("eth_chainId", []), 16) != SEPOLIA_CHAIN_ID:
        raise SystemExit("SEPOLIA_RPC_URL is not a Sepolia endpoint")
    latest = int(rpc("eth_blockNumber", []), 16)
    print(f"Staking {CONFIG.staking_address}: scanning blocks {a.from_block:,}..{latest:,}")
    logs = staked_logs(a.from_block, latest, a.step)
    stakes = Counter(to_checksum_address("0x" + log["topics"][1][-40:]) for log in logs)
    if not stakes:
        print("No Staked events found. Stake some TRK from the app first, then run this again.")
        return

    reader = StakingReader(ReadOnlyRpc(CONFIG.sepolia_rpc_url, CONFIG.http_timeout), CONFIG.staking_address)
    print(f"\n{'wallet':42}  stakes  open  locked")
    for wallet, n in stakes.most_common():
        s = reader.wallet_state(wallet)
        open_ = [p for p in s["positions"] if not p.withdrawn]
        locked = [p for p in open_ if p.unlock_time > s["block_timestamp"]]
        print(f"{wallet}  {n:>6}  {len(open_):>4}  {len(locked):>6}")
    print("\nPick a wallet with open positions (ideally one still locked) and set EVAL_WALLET in .env.")


if __name__ == "__main__":
    main()
