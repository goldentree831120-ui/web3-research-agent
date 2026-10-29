"""Every tool call is appended to logs/tool_calls.jsonl: when, which tool, arguments,
how long it took, whether it failed, and how big the result was. The eval reads this log
to compute tool-selection accuracy, so the numbers come from what actually ran."""
import functools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

_run_id = {"value": None}
_log_path: dict[str, Path | None] = {"value": None}


def set_log_path(path: Path):
    """Where tool calls are written. Read at call time, so tests and the eval can redirect it."""
    _log_path["value"] = path


def set_run_id(run_id: str | None):
    _run_id["value"] = run_id


def logged(default_path: Path):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            entry = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": _run_id["value"],
                     "tool": fn.__name__, "args": kwargs or list(args)}
            try:
                result = fn(*args, **kwargs)
                entry.update(ok=True, result_chars=len(str(result)))
                return result
            except Exception as e:
                entry.update(ok=False, error=f"{type(e).__name__}: {e}")
                raise
            finally:
                entry["ms"] = round((time.perf_counter() - start) * 1000, 1)
                log_path = _log_path["value"] or default_path
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
        return wrapper
    return deco
