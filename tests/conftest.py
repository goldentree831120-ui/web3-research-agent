import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_log(tmp_path):
    """Each test writes tool logs to its own file, never to logs/."""
    from agent.toollog import set_log_path
    log = tmp_path / "tool_calls.jsonl"
    set_log_path(log)
    yield log
    set_log_path(None)
