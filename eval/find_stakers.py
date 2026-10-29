#!/usr/bin/env python3
"""List wallets that have staked in the current Sepolia staking contract, to pick EVAL_WALLET.

    python -m eval.find_stakers                  # scan the contract's history for stakers
    python -m eval.find_stakers --check 0xABC... # just show one address's positions

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

# Some free endpoints drop old event logs ("pruned history"); these are tried in order for
# eth_getLogs only. All public, no key. Put your own endpoint first with --logs-rpc.
LOG_ENDPOINTS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://sepolia.drpc.org",
    "https://1rpc.io/sepolia",
    "https://sepolia.gateway.tenderly.co",
    "https://ethereum-sepolia.rpc.subquery.network/public",
]


def rpc(url: str, method: str, params: list):
    assert method in {"eth_chainId", "eth_blockNumber", "eth_getLogs"}  # reads only
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=CONFIG.http_timeout)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body["result"]


def logs_from(url: str, start: int, end: int, step: int) -> list:
    if int(rpc(url, "eth_chainId", []), 16) != SEPOLIA_CHAIN_ID:
        raise RuntimeError("not a Sepolia endpoint")
    logs, lo = [], start
    while lo <= end:
        hi = min(lo + step - 1, end)
        try:
            logs += rpc(url, "eth_getLogs", [{"address": CONFIG.staking_address, "topics": [STAKED_TOPIC],
                                              "fromBlock": hex(lo), "toBlock": hex(hi)}])
            lo = hi + 1
        except (RuntimeError, requests.RequestException) as e:
            if "prun" in str(e).lower() or step <= 1000:
                raise  # history not kept here, or still failing on small ranges: next endpoint
            step //= 2  # the endpoint limits the block range; try smaller windows
            print(f"    range limit ({str(e)[:60]}); using {step}-block windows")
    return logs


def staked_logs(endpoints: list[str], start: int, end: int, step: int) -> list:
    for url in endpoints:
        print(f"  trying {url}")
        try:
            logs = logs_from(url, start, end, step)
            print(f"  ok: {len(logs)} Staked event(s)")
            return logs
        except (RuntimeError, requests.RequestException, ValueError) as e:
            print(f"    failed: {str(e)[:100]}")
    raise SystemExit("No endpoint returned the logs. Use --check with an address you staked from instead.")


def show(reader: StakingReader, wallet: str, stakes: int | str = "-"):
    s = reader.wallet_state(wallet)
    open_ = [p for p in s["positions"] if not p.withdrawn]
    locked = [p for p in open_ if p.unlock_time > s["block_timestamp"]]
    print(f"{s['wallet']}  {str(stakes):>6}  {len(s['positions']):>9}  {len(open_):>4}  {len(locked):>6}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="ADDRESS", help="only show this public address's positions")
    ap.add_argument("--logs-rpc", help="extra endpoint to try first for the history scan")
    ap.add_argument("--from-block", type=int, default=DEPLOY_BLOCK)
    ap.add_argument("--step", type=int, default=10_000)
    a = ap.parse_args()

    reader = StakingReader(ReadOnlyRpc(CONFIG.sepolia_rpc_url, CONFIG.http_timeout), CONFIG.staking_address)
    header = f"\n{'wallet':42}  {'stakes':>6}  {'positions':>9}  {'open':>4}  {'locked':>6}"
    if a.check:
        print(header)
        show(reader, a.check.strip())
        return

    endpoints = ([a.logs_rpc] if a.logs_rpc else []) + LOG_ENDPOINTS
    latest = int(rpc(endpoints[0], "eth_blockNumber", []), 16)
    print(f"Staking {CONFIG.staking_address}: scanning blocks {a.from_block:,}..{latest:,}")
    logs = staked_logs(endpoints, a.from_block, latest, a.step)
    stakes = Counter(to_checksum_address("0x" + log["topics"][1][-40:]) for log in logs)
    if not stakes:
        print("No Staked events found. Stake some TRK from the app first, then run this again.")
        return
    print(header)
    for wallet, n in stakes.most_common():
        show(reader, wallet, n)
    print("\nPick a wallet with open positions (ideally one still locked) and set EVAL_WALLET in .env.")


if __name__ == "__main__":
    main()
