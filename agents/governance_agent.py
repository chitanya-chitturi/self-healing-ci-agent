"""Governance Agent: the approval gate between a proposed fix and it ever
reaching a watched repo. Only called when the Remediation Agent actually
proposed something — if it didn't, there's nothing to approve and the
Orchestrator goes straight to the Notifier's diagnosis path.

Every call returns a verdict AND the reasoning behind it, so it can be
written to the audit log regardless of outcome.
"""
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yml"


def load_policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text())


def evaluate(policy: dict, repo: str, triage_result: dict, proposed_fix: dict) -> dict:
    if not policy.get("enabled", False):
        return {"approved": False, "reasoning": "Global kill switch is disabled in policy.yml."}

    repo_cfg = policy.get("repos", {}).get(repo)
    if repo_cfg is None or not repo_cfg.get("enabled", False):
        return {
            "approved": False,
            "reasoning": f"Repo {repo} is not explicitly enabled in policy.yml — "
            "default is deny.",
        }

    category = triage_result["category"]
    if category not in policy.get("auto_fix_categories", []):
        return {
            "approved": False,
            "reasoning": f"Category '{category}' is not in auto_fix_categories.",
        }

    confidence = triage_result.get("confidence", 0.0)
    min_confidence = policy.get("min_confidence", 1.0)
    if confidence < min_confidence:
        return {
            "approved": False,
            "reasoning": f"Triage confidence {confidence:.2f} is below the "
            f"required {min_confidence:.2f}.",
        }

    files_changed = proposed_fix.get("files_changed", 999)
    max_files = policy.get("max_files_changed", 0)
    if files_changed > max_files:
        return {
            "approved": False,
            "reasoning": f"Proposed fix touches {files_changed} file(s), exceeding "
            f"the max_files_changed limit of {max_files}.",
        }

    return {
        "approved": True,
        "reasoning": f"Category '{category}' is auto-fixable, confidence "
        f"{confidence:.2f} >= {min_confidence:.2f}, and the fix touches only "
        f"{files_changed} file(s). All policy checks passed.",
    }
