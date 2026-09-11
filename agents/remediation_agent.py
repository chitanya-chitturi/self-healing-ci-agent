"""Remediation Agent: proposes a fix, never applies one.

Deliberately narrow — a real regression-revert, not code generation. Only
ever proposes something when the category is dependency_issue AND the most
recent commit touched exactly one known dependency-manifest file, so the
"fix" is a confident, mechanical revert of that one file to its
last-known-good (parent-commit) content. Everything else — infra_flaky,
app_bug, or a break that can't be pinned on the latest commit — returns None
and falls through to the Notifier's diagnosis path instead.
"""
from pathlib import Path

from lib.github_client import GitHubClient

MANIFEST_FILENAMES = {
    "pom.xml",
    "package.json",
    "requirements.txt",
    "build.gradle",
    "build.gradle.kts",
}


def propose_fix(client: GitHubClient, repo: str, run: dict, triage_result: dict) -> dict | None:
    if triage_result["category"] != "dependency_issue":
        return None

    head_sha = run["head_sha"]
    commit = client.get_commit(repo, head_sha)
    parents = commit.get("parents", [])
    if not parents:
        return None
    parent_sha = parents[0]["sha"]

    diff = client.compare_commits(repo, parent_sha, head_sha)
    changed_manifests = [
        f for f in diff.get("files", []) if Path(f["filename"]).name in MANIFEST_FILENAMES
    ]
    if len(changed_manifests) != 1:
        # Not confidently attributable to a single manifest change in the
        # last commit — don't guess.
        return None

    file_path = changed_manifests[0]["filename"]
    known_good = client.get_file(repo, file_path, parent_sha)
    current = client.get_file(repo, file_path, head_sha)

    return {
        "file_path": file_path,
        "revert_to_content": known_good["content"],
        "current_blob_sha": current["sha"],
        "files_changed": 1,
        "summary": f"Revert {file_path} to its state before commit {head_sha[:7]}, "
        f"which introduced the dependency change that broke the build.",
        "base_branch_sha": head_sha,
    }
