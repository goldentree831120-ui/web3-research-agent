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

Default model: `groq:llama-3.3-70b-versatile` on Groq's free tier (no card; over the limit it
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

**Results: not run yet.** Fill this from your own run; no numbers are claimed until then.

| Model | Tool selection | Refusals | False refusals | Answers correct (hand) | Median latency |
|---|---|---|---|---|---|
| _run it_ | | | | | |

## Honest limitations

- Three tools, one contract, one testnet. It demonstrates tool calling and guardrails; it is not a
  general Web3 analyst.
- Retrieval is keyword-based (BM25), so paraphrased questions with no shared words can miss.
- Write requests can't succeed because there is no write path at all, whatever the model does.
  The model's *refusal message* is still model-dependent, and that is what q17–q19 measure.
- 20 questions is small. Per-category numbers cover 1–5 questions each; treat them as anecdotes.
- Answer correctness is graded by me, by hand, against the `check` column.
- Prices come from CoinGecko's public API (rate-limited, no SLA).
