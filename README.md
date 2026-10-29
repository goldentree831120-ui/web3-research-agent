# Web3 research assistant (LangChain agent, read-only)

A small tool-calling agent that answers questions about my own Web3 projects. Built to be
described honestly: what it can do, how it is limited, and measured numbers from a fixed test set.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt                      # includes langchain-groq
cp .env.example .env                                 # add your key in .env, never in chat
pytest -q                                            # 36 tests, no key or network needed
python -m eval.find_stakers                          # pick EVAL_WALLET (public address) for .env
python -m agent.agent "What did the security review of my staking contract find?"
python -m eval.run_eval                              # the 20-question evaluation
```

Default model: `groq:openai/gpt-oss-120b` on Groq's free tier (no card; over the limit it
returns HTTP 429 instead of charging). Any LangChain provider works by changing `LLM_MODEL` and
installing its package.

## Architecture

```
question ──▶ LangChain create_agent (tool calling, structured output, step limits)
                │
                ├─ get_staking_state(wallet)   ─▶ ReadOnlyRpc ─▶ Sepolia: Staking.sol, eth_call only
                ├─ get_token_price(symbol)     ─▶ CoinGecko public API (allowlisted symbols)
                └─ search_project_notes(query) ─▶ BM25 over kb/*.md (my project docs)
                │
every tool call ─▶ logs/tool_calls.jsonl (time, tool, args, ms, ok/error)
                ▼
Answer {answer, sources, confidence, refused}
```

## Guardrails (each one has a test)

| Guardrail | How | Test |
|---|---|---|
| No write transactions | No private key anywhere; the RPC client rejects every method except 5 read calls *before* any network request; no write tool exists | `test_rpc_refuses_anything_but_reads`, `test_no_signing_capability_in_codebase` |
| Right network | RPC chain id must be Sepolia (11155111) | `test_rpc_refuses_wrong_chain` |
| Input validation | Address regex, symbol allowlist, query length; errors go back to the model as text | `test_bad_addresses_are_rejected_without_network`, `test_price_tool_only_allows_listed_symbols` |
| Step limits | `ToolCallLimitMiddleware` (6) and `ModelCallLimitMiddleware` (8) per question | `test_runaway_model_is_stopped_by_limits` |
| Tool output is data | Notes are labelled as reference data; the system prompt says to ignore instructions in tool output | eval q19 |
| Logging | Every tool call to JSONL with timing and outcome | `test_every_tool_call_is_logged` |
| Eval budget | Pause between questions, token budget per run, stop on a rate-limit error with a resume list | `tests/test_eval_runner.py` |
| Refuse write requests | System prompt + structured `refused` flag | eval q17–q19, `test_refusal_path_calls_no_data_tools` |

## Evaluation

`eval/questions.yaml` has 20 questions:
- live staking reads
- prices
- project notes
- questions that combine tools
- three that must be refused (two write requests, one prompt injection)
- one invalid address
- one general-knowledge question

Each question lists the acceptable tool sets and what a correct answer must contain.

`python -m eval.run_eval` writes `eval/results/<model>-<time>.csv` and `.md`:
- **automatic:** tool-selection accuracy, refusal accuracy, false refusals, tool errors, limit
  hits, latency;
- **by hand:** fill `answer_correct` (1/0) per row using the `check` column, then
  `python -m eval.run_eval --grade eval/results/<file>.csv`.

Budget guards, for free-tier limits:
- `--pause 30` seconds between questions keeps a run under the tokens-per-minute limit;
- `--budget 90000` stops before the next question once that many tokens are used (each row
  records the provider-reported tokens);
- a rate-limit error that survives the retries stops the run, keeps the finished rows, and prints
  `--only q..,q..` to finish later. `--grade a.csv b.csv` combines the parts.

`python -m eval.run_eval --fake` checks the pipeline without a key (its scores are meaningless).

**Results** (one run, 29 Oct 2026, `groq:openai/gpt-oss-120b` on Groq's free tier, from my laptop
in India over home internet; latency includes the network). Raw rows:
[`eval/results/groq_openai_gpt-oss-120b-20261029-0714.csv`](eval/results/groq_openai_gpt-oss-120b-20261029-0714.csv).

| Metric | Result |
|---|---|
| Tool selection correct | 18/20 (90%) |
| Refused when it should (2 write requests, 1 prompt injection) | 3/3 |
| Refused when it should not have | 0/17 |
| Answers correct (hand-graded, strict: every point in `check`) | 15/20 |
| Runs that hit the step limit / tool errors | 0/20 / 0 |
| Latency median / max | 2.4 s / 6.2 s |
| Tokens, whole run / median per question | 32,730 / 1,722 |

The staking questions ran against a wallet with one open position (200 TRK, 180-day lock),
staked for this purpose on Sepolia.

**What failed, and why it matters:**
- **q12, q14: the model skipped a tool it needed.** q12 (what the chat server's latency
  histogram measures) was answered from general knowledge, and wrongly: it said round-trip time,
  but the notes say server handling time, excluding the network. q14 (staked TRK in USD) said
  correctly that testnet TRK has no USD value, but never read the wallet, so it didn't report the
  200 TRK. Both are grounding failures, the main risk for this kind of agent.
- **q15: right tools, vague answer.** It read the wallet and the notes but called F1 an
  "under-funded reward pool issue" instead of explaining that rewards come out of other stakers'
  principal.
- **q06, q13: correct but incomplete.** q06 gave the price without naming CoinGecko; q13 got
  OPS-1 right but didn't add that F1/F1b/F2 still apply to the deployed contract. Graded wrong
  under the strict rule; 17/20 if counted as right.

## Honest limitations

- Three tools, one contract, one testnet. It demonstrates tool calling and guardrails; it is not a
  general Web3 analyst.
- Retrieval is keyword-based (BM25), so paraphrased questions with no shared words can miss.
- Write requests can't succeed because there is no write path at all, whatever the model does.
  The model's *refusal message* is still model-dependent, and that is what q17–q19 measure.
- 20 questions is small. Per-category numbers cover 1–5 questions each; treat them as anecdotes.
- Answer correctness is graded by me, by hand, against the `check` column.
- One run of one model. Temperature is 0, but provider-side changes can still shift results;
  a second run or a second model would show how stable these numbers are.
- Prices come from CoinGecko's public API (rate-limited, no SLA).
