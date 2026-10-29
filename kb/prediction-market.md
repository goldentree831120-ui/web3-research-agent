# Prediction Market & Market Intel Lab

Status: **M1** binary-outcome market contract done. Next: M2 pricing, M3 read-only
data pipeline, M4 calibration study, M5 news event study, M6 dashboard + note.

```bash
forge test                      # 19 unit/fuzz tests + 5 invariants
./script/mutation-check.sh      # plants 6 bugs; the suite must catch each
```
(OpenZeppelin v5.1.0 and forge-std are included in `lib/`. On Windows use WSL or Git Bash.)

## M1: `BinaryMarket`

One yes/no question on a test ERC-20 collateral.

- **Complete sets.** `mintSets(x)`: deposit x collateral, get x YES + x NO. `redeemSets(x)`:
  return x of each, get x back, in any phase. A set is always worth exactly 1, so the
  market is solvent without knowing any price.
- **Lifecycle.** Open until `closeTime`. Then the **resolver** proposes Yes, No or Invalid.
  During the **dispute window** anyone can dispute by posting a bond. An undisputed proposal
  is finalized by anyone after the window. A disputed one goes to the **arbiter**: if
  overturned the disputer gets the bond back, if upheld it goes to the resolver.
- **Payout.** After Final, `redeem()` burns all your YES and NO: Yes pays 1 per YES, No pays
  1 per NO, Invalid pays 0.5 per token (rounded down).
- **Liveness.** If the resolver never proposes (30 days after close) or the arbiter never
  rules (30 days after the window), anyone can finalize as Invalid and the bond is returned.
  Funds can't be locked forever by a silent role.
- **Fee-on-transfer collateral.** Sets are minted for what actually arrived, not what was asked.

### What the tests prove

| Invariant | Meaning |
|---|---|
| `collateralCoversOutstandingSets` | balance >= what holders could claim right now + any dispute bond (the brief's invariant) |
| `setsStayPairedUntilFinal` | YES supply == NO supply until resolution |
| `collateralAccounting` | balance == deposits + bonds in − redemptions − payouts − bonds out, exactly |
| `noOverpayment` | no redeem ever paid more than the tokens were worth (checked by an independent formula) |
| `roundingDustIsBounded` | rounding strands at most 1 wei per Invalid redemption, always in the market's favour |

The handler mints, trades YES and NO between four users (so balances become uneven),
redeems sets, and drives proposals, disputes, arbitration, finalization and payouts in
random order. `docs/mutation-report.txt`: all six planted bugs are caught.

### Trust and limitations (honest list)

- The **resolver and arbiter are trusted.** The dispute window and bond make a wrong report
  cost something and give time to react; they do not make the oracle trustless. A real system
  would use an optimistic oracle (e.g. UMA) or a decentralized arbiter.
- One market per contract, no factory, no fees, no trading mechanism yet (M2).
- The dispute bond is fixed and the first disputer wins the slot; a richer design would let
  bonds escalate.
- Minting after close is blocked (people would mint once the answer is known); trading the
  outcome tokens after close is not, because they are ordinary ERC-20s.
