"""Orchestrator: polls every watched repo for new failed workflow runs and
drives each one through Triage -> (Remediation -> Governance) -> Notifier.

Run with: python -m agents.orchestrator   (from the repo root)
"""
import traceback
from pathlib import Path

import yaml

from agents import governance_agent, notifier_agent, remediation_agent, triage_agent
from lib import audit_log, state
from lib.github_client import GitHubClient

WATCHED_REPOS_PATH = Path(__file__).resolve().parent.parent / "config" / "watched_repos.yml"


def load_watched_repos() -> list[str]:
    return yaml.safe_load(WATCHED_REPOS_PATH.read_text())["repos"]


def process_failure(client: GitHubClient, policy: dict, repo: str, run: dict) -> None:
    log_text = client.get_run_log_text(repo, run["id"])
    triage_result = triage_agent.classify(log_text)
    audit_log.record(
        {"stage": "triage", "repo": repo, "run_id": run["id"], "run_url": run["html_url"], **triage_result}
    )

    if triage_result["category"] == "infra_flaky":
        notifier_agent.flag_flaky(client, repo, run, triage_result)
        audit_log.record({"stage": "notify", "action": "flag_flaky", "repo": repo, "run_id": run["id"]})
        return

    proposed_fix = remediation_agent.propose_fix(client, repo, run, triage_result)
    if proposed_fix is None:
        notifier_agent.post_diagnosis_issue(client, repo, run, triage_result)
        audit_log.record(
            {
                "stage": "notify",
                "action": "diagnosis_issue",
                "repo": repo,
                "run_id": run["id"],
                "reason": "no fix proposed by remediation agent",
            }
        )
        return

    audit_log.record(
        {
            "stage": "remediation",
            "repo": repo,
            "run_id": run["id"],
            "file_path": proposed_fix["file_path"],
            "summary": proposed_fix["summary"],
        }
    )

    governance_result = governance_agent.evaluate(policy, repo, triage_result, proposed_fix)
    audit_log.record({"stage": "governance", "repo": repo, "run_id": run["id"], **governance_result})

    if governance_result["approved"]:
        pr = notifier_agent.open_remediation_pr(client, repo, run, triage_result, proposed_fix, governance_result)
        audit_log.record(
            {"stage": "notify", "action": "opened_pr", "repo": repo, "run_id": run["id"], "pr_url": pr.get("html_url")}
        )
    else:
        issue = notifier_agent.post_diagnosis_issue(client, repo, run, triage_result, governance_result)
        audit_log.record(
            {
                "stage": "notify",
                "action": "diagnosis_issue",
                "repo": repo,
                "run_id": run["id"],
                "issue_url": issue.get("html_url"),
                "reason": "governance blocked",
            }
        )


def main() -> None:
    client = GitHubClient()
    policy = governance_agent.load_policy()

    for repo in load_watched_repos():
        last_checked = state.get_last_checked_run_id(repo)
        runs = client.list_recent_runs(repo)
        if not runs:
            continue

        max_id_seen = max(r["id"] for r in runs)
        new_failed_runs = sorted(
            (r for r in runs if r["id"] > last_checked and r["conclusion"] == "failure"),
            key=lambda r: r["id"],
        )

        for run in new_failed_runs:
            try:
                process_failure(client, policy, repo, run)
            except Exception as exc:  # one bad run should never kill the whole poll
                audit_log.record(
                    {
                        "stage": "error",
                        "repo": repo,
                        "run_id": run["id"],
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )

        state.set_last_checked_run_id(repo, max_id_seen)


if __name__ == "__main__":
    main()
