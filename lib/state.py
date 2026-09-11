"""Per-repo state: the highest workflow-run id already processed, so the
orchestrator never reprocesses (and re-opens duplicate PRs/Issues for) the
same failure on every scheduled poll. Committed back to this agent's own
repo by the workflow after each run — no external database needed.
"""
import json
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def _state_path(repo: str) -> Path:
    return STATE_DIR / f"{repo.replace('/', '__')}.json"


def get_last_checked_run_id(repo: str) -> int:
    path = _state_path(repo)
    if not path.exists():
        return 0
    return json.loads(path.read_text()).get("last_checked_run_id", 0)


def set_last_checked_run_id(repo: str, run_id: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(repo)
    path.write_text(json.dumps({"last_checked_run_id": run_id}, indent=2) + "\n")
