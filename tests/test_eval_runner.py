"""The eval runner's budget guards: they decide how much of the free-tier quota a run can use."""
import csv

import pytest

import eval.run_eval as ev

WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


class RateLimitError(Exception):
    """Same class name as the provider SDK's 429 error."""


def fake_result(tokens):
    return {"answer": {"answer": "ok", "sources": [], "confidence": "high", "refused": False},
            "tool_calls": [], "tool_errors": [], "hit_limit": False, "model_calls": 1, "tokens": tokens}


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "RESULTS", tmp_path)
    monkeypatch.setattr(ev, "build_agent", lambda: object())
    monkeypatch.setenv("EVAL_WALLET", WALLET)
    asked = []

    def use(answers):
        def ask(question, agent, run_id):
            asked.append(run_id)
            a = answers[len(asked) - 1]
            if isinstance(a, Exception):
                raise a
            return fake_result(a)
        monkeypatch.setattr(ev, "ask", ask)
        return asked
    return use


def rows(tmp_path):
    (path,) = tmp_path.glob("*.csv")
    return list(csv.DictReader(open(path)))


def test_budget_stops_before_the_next_question(runner, tmp_path, capsys):
    asked = runner([40_000, 40_000, 40_000, 40_000])
    ev.run(fake=False, only=None, pause=0, budget=70_000)
    assert asked == ["q01", "q02"]  # 80k used after q02, so q03 never starts
    assert [r["id"] for r in rows(tmp_path)] == ["q01", "q02"]
    out = capsys.readouterr().out
    assert "token budget reached" in out and "--only q03,q04," in out


def test_rate_limit_stops_the_run_and_keeps_finished_rows(runner, tmp_path, capsys):
    asked = runner([1000, RateLimitError("Error code: 429 - daily limit")])
    ev.run(fake=False, only=None, pause=0, budget=10**9)
    assert asked == ["q01", "q02"]
    assert [r["id"] for r in rows(tmp_path)] == ["q01"]  # the rate-limited question isn't scored
    assert "--only q02,q03" in capsys.readouterr().out


def test_other_errors_are_recorded_not_fatal(runner, tmp_path):
    runner([ValueError("boom")] + [100] * 19)
    ev.run(fake=False, only=None, pause=0, budget=10**9)
    r = rows(tmp_path)
    assert len(r) == 20 and r[0]["answer"] == "ValueError: boom" and r[0]["tool_choice_correct"] == "0"


def test_only_runs_the_listed_questions(runner, tmp_path):
    asked = runner([10, 10])
    ev.run(fake=False, only={"q05", "q17"}, pause=0, budget=10**9)
    assert asked == ["q05", "q17"]


def test_real_run_requires_a_public_wallet(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "RESULTS", tmp_path)
    monkeypatch.setenv("EVAL_WALLET", "not-an-address")
    with pytest.raises(SystemExit, match="EVAL_WALLET"):
        ev.run(fake=False, only=None, pause=0, budget=1)


def test_grade_combines_several_result_files(runner, tmp_path, monkeypatch):
    runner([10] * 20)
    ev.run(fake=False, only={"q01"}, pause=0, budget=10**9)
    first = next(tmp_path.glob("*.csv"))
    second = tmp_path / "second.csv"
    second.write_text(first.read_text().replace("q01", "q02"))
    ev.summarize([first, second])
    md = (tmp_path / f"{first.stem}-combined.md").read_text()
    assert "2 question(s): q01, q02" in md
