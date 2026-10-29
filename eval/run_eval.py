#!/usr/bin/env python3
"""Run the 20 test questions and measure the agent.

    python -m eval.run_eval                  # real model from .env (Groq free tier: no charge)
    python -m eval.run_eval --only q05,q06   # just these questions (e.g. to finish a stopped run)
    python -m eval.run_eval --fake           # pipeline check, no key needed (scores will be bad)
    python -m eval.run_eval --grade eval/results/a.csv [b.csv ...]   # after hand-grading

Budget guards (free-tier limits are per minute and per day):
  --pause S     seconds to wait between questions (default 30), keeps under tokens-per-minute
  --budget N    stop before the next question once N tokens are used (default 90,000)
  a rate-limit error that survives the SDK's retries stops the run; the CSV keeps what finished,
  and the summary prints the --only list to resume with later.

Measured automatically: tool-selection accuracy, refusal accuracy, tool errors, limit hits,
latency, tokens. Answer correctness is hand-graded: fill the `answer_correct` column (1/0) in the
CSV, then run --grade. Every number in the summary comes with its count (k/N).
"""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

import os
import re

import yaml

from agent.agent import ask, build_agent
from agent.config import CONFIG
from agent.toollog import set_log_path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
FIELDS = ["id", "question", "accepted_tool_sets", "tools_called", "tool_choice_correct", "should_refuse",
          "refused", "refusal_correct", "tool_errors", "hit_limit", "model_calls", "tokens", "seconds", "answer", "sources",
          "confidence", "check", "answer_correct"]


def load(wallet: str):
    spec = yaml.safe_load((HERE / "questions.yaml").read_text())
    return [{**q, "question": q["question"].format(wallet=wallet)} for q in spec["questions"]]


def is_rate_limit(e: Exception) -> bool:
    return "RateLimit" in type(e).__name__ or "429" in str(e) or "rate limit" in str(e).lower()


def run(fake: bool, only: set[str] | None, pause: float, budget: int):
    if fake:
        from tests.fakes import ScriptedModel, final
        agent = build_agent(ScriptedModel(script=[final("(fake model)", confidence="low")]))
        label, wallet = "fake", "0x" + "0" * 39 + "1"
    else:
        wallet = os.getenv("EVAL_WALLET", "").strip()
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet):
            raise SystemExit("Set EVAL_WALLET in .env to a public address with staking positions "
                             "(python -m eval.find_stakers lists them).")
        agent = build_agent()
        label = CONFIG.llm_model.replace(":", "_").replace("/", "_")
    questions = [q for q in load(wallet) if not only or q["id"] in only]
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = RESULTS / f"{label}-{stamp}.csv"
    set_log_path(RESULTS / f"{label}-{stamp}.tool_calls.jsonl")
    rows, used, stopped = [], 0, None
    for i, q in enumerate(questions):
        if used >= budget:
            stopped = f"token budget reached ({used:,} >= {budget:,})"
            break
        if i and pause and not fake:
            time.sleep(pause)
        t0 = time.perf_counter()
        try:
            r = ask(q["question"], agent=agent, run_id=q["id"])
            err = None
        except Exception as e:  # a crash is a result too
            if is_rate_limit(e):
                stopped = f"rate limit at {q['id']}: {type(e).__name__}"
                break
            r, err = None, f"{type(e).__name__}: {e}"
        secs = round(time.perf_counter() - t0, 2)
        used += r["tokens"] if r else 0
        called = sorted({c["name"] for c in (r["tool_calls"] if r else []) if c["name"] != "Answer"})
        accepted = [sorted(set(a)) for a in q["accept"]]
        should_refuse = bool(q.get("refuse"))
        refused = bool(r and r["answer"].get("refused"))
        rows.append({
            "id": q["id"], "question": q["question"], "accepted_tool_sets": json.dumps(accepted),
            "tools_called": json.dumps(called), "tool_choice_correct": int(r is not None and called in accepted),
            "should_refuse": int(should_refuse), "refused": int(refused),
            "refusal_correct": int(refused == should_refuse) if r else 0,
            "tool_errors": len(r["tool_errors"]) if r else "", "hit_limit": int(r["hit_limit"]) if r else "",
            "model_calls": r["model_calls"] if r else "", "tokens": r["tokens"] if r else "",
            "seconds": secs, "answer": err or r["answer"]["answer"],
            "sources": "; ".join(r["answer"].get("sources", [])) if r else "",
            "confidence": r["answer"].get("confidence", "") if r else "", "check": q["check"], "answer_correct": "",
        })
        print(f"{q['id']}: tools={called} choice_ok={rows[-1]['tool_choice_correct']} "
              f"tokens={rows[-1]['tokens']} ({secs}s; {used:,} tokens so far)")
    if not rows:
        raise SystemExit(f"Stopped before any question finished: {stopped}")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if stopped:
        done = {r["id"] for r in rows}
        rest = [q["id"] for q in questions if q["id"] not in done]
        print(f"\nSTOPPED: {stopped}. Not run: {len(rest)} question(s).")
        print(f"Resume later (Groq's daily limits reset at 00:00 UTC) with:\n"
              f"  python -m eval.run_eval --only {','.join(rest)}")
    summarize([out])


def summarize(paths: list[Path]):
    rows = [r for p in paths for r in csv.DictReader(open(p))]
    path = paths[0] if len(paths) == 1 else paths[0].with_name(paths[0].stem + "-combined.csv")
    n = len(rows)
    tool_ok = sum(int(r["tool_choice_correct"]) for r in rows)
    ref = [r for r in rows if r["should_refuse"] == "1"]
    ref_ok = sum(int(r["refusal_correct"]) for r in ref)
    false_ref = sum(1 for r in rows if r["should_refuse"] == "0" and r["refused"] == "1")
    graded = [r for r in rows if r["answer_correct"] in ("0", "1")]
    ans_ok = sum(int(r["answer_correct"]) for r in graded)
    secs = sorted(float(r["seconds"]) for r in rows)
    lines = [
        f"# Eval: {', '.join(p.stem for p in paths)}", "",
        f"{n} question(s): {', '.join(r['id'] for r in rows)}", "",
        "| Metric | Result |", "|---|---|",
        f"| Tool selection correct | {tool_ok}/{n} ({100 * tool_ok / n:.0f}%) |",
        f"| Refused when it should (write requests, injection) | {ref_ok}/{len(ref)} |",
        f"| Refused when it should NOT have | {false_ref}/{n - len(ref)} |",
        f"| Answers correct (hand-graded) | {f'{ans_ok}/{len(graded)}' if graded else 'not graded yet'} |",
        f"| Runs that hit the step limit | {sum(r['hit_limit'] == '1' for r in rows)}/{n} |",
        f"| Tool errors returned to the model | {sum(int(r['tool_errors'] or 0) for r in rows)} |",
        f"| Latency median / max | {secs[n // 2]:.1f}s / {secs[-1]:.1f}s |",
        f"| Tokens total / median per question | {sum(int(r.get('tokens') or 0) for r in rows):,} / "
        f"{sorted(int(r.get('tokens') or 0) for r in rows)[n // 2]:,} |", "",
        "## Failures", "",
    ]
    for r in rows:
        problems = []
        if r["tool_choice_correct"] != "1":
            problems.append(f"tools {r['tools_called']} not in {r['accepted_tool_sets']}")
        if r["refusal_correct"] != "1":
            problems.append(f"refused={r['refused']} expected={r['should_refuse']}")
        if r["answer_correct"] == "0":
            problems.append("answer wrong")
        if problems:
            lines.append(f"- **{r['id']}** {r['question']}: {'; '.join(problems)}")
    md = path.with_suffix(".md")
    md.write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="no LLM: checks the pipeline only")
    ap.add_argument("--only", help="comma-separated question ids, e.g. q05,q06")
    ap.add_argument("--pause", type=float, default=30, help="seconds between questions (default 30)")
    ap.add_argument("--budget", type=int, default=90_000, help="stop once this many tokens are used")
    ap.add_argument("--grade", type=Path, nargs="+", help="re-summarize result CSV(s) after hand-grading")
    a = ap.parse_args()
    if a.grade:
        summarize(a.grade)
    else:
        run(a.fake, set(a.only.split(",")) if a.only else None, a.pause, a.budget)
