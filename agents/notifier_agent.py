"""Notifier Agent: the only agent that actually talks to a watched repo's
issue tracker / pull requests. Three distinct actions, one per outcome:

- open_remediation_pr: governance approved a fix.
- flag_flaky: infra_flaky classification, no code change, just a heads-up.
- post_diagnosis_issue: app_bug, low confidence, or governance blocked the
  fix — a human needs to look at this. Tags the failing commit's author as
  the primary "likely developer" signal, with a best-effort file-level
  blame lookup added as supplementary context only.
"""
import re

from lib.github_client import GitHubClient

# Matches a fully-qualified Java class reference: one or more lowercase
# package segments followed by exactly one capitalized class-name segment —
# stops there, so a trailing ".methodName" isn't swept into the path.
_JAVA_CLASS_RE = re.compile(r"\b((?:[a-z][a-zA-Z0-9_]*\.)+[A-Z][a-zA-Z0-9_]*)\b")


def _guess_java_paths(root_cause: str) -> list[str]:
    """Best-effort: turn a dotted Java class reference in the diagnosis text
    into plausible source paths under the standard Maven layout."""
    paths = []
    for match in set(_JAVA_CLASS_RE.findall(root_cause)):
        rel = match.replace(".", "/") + ".java"
        paths.append(f"src/main/java/{rel}")
        paths.append(f"src/test/java/{rel}")
    return paths


def _blame_context(client: GitHubClient, repo: str, run: dict, triage_result: dict) -> str:
    for path in _guess_java_paths(triage_result.get("root_cause", "")):
        commit = client.last_commit_touching_path(repo, path, run["head_sha"])
        if commit:
            author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
            return f"\n\n_Supplementary context: `{path}` was last changed by {author} in {commit['sha'][:7]}._"
    return ""


def open_remediation_pr(
    client: GitHubClient, repo: str, run: dict, triage_result: dict,
    proposed_fix: dict, governance_result: dict,
) -> dict:
    branch = f"agent-fix/{run['id']}"
    client.create_branch(repo, branch, proposed_fix["base_branch_sha"])
    client.update_file(
        repo,
        proposed_fix["file_path"],
        f"Auto-fix: revert {proposed_fix['file_path']} ({triage_result['category']})",
        proposed_fix["revert_to_content"],
        branch,
        proposed_fix["current_blob_sha"],
    )
    body = (
        f"**Triage classification:** `{triage_result['category']}` "
        f"(confidence {triage_result['confidence']:.2f})\n\n"
        f"**Root cause:** {triage_result['root_cause']}\n\n"
        f"**Fix:** {proposed_fix['summary']}\n\n"
        f"**Governance:** approved — {governance_result['reasoning']}\n\n"
        f"---\n_Opened automatically by the self-healing CI agent in response to "
        f"[run #{run['id']}]({run['html_url']})._"
    )
    return client.create_pull_request(
        repo,
        title=f"🤖 Auto-fix: {triage_result['category']} ({proposed_fix['file_path']})",
        body=body,
        head=branch,
    )


def flag_flaky(client: GitHubClient, repo: str, run: dict, triage_result: dict) -> dict:
    body = (
        f"🤖 The self-healing CI agent classified this failure as **flaky** "
        f"(confidence {triage_result['confidence']:.2f}), not a real bug: "
        f"{triage_result['root_cause']}\n\n"
        f"No code change proposed — recommend quarantining/retrying rather than patching. "
        f"See [run #{run['id']}]({run['html_url']})."
    )
    return client.create_commit_comment(repo, run["head_sha"], body)


def post_diagnosis_issue(
    client: GitHubClient, repo: str, run: dict, triage_result: dict,
    governance_result: dict | None = None,
) -> dict:
    commit = client.get_commit(repo, run["head_sha"])
    author_login = (commit.get("author") or {}).get("login")
    author_name = commit.get("commit", {}).get("author", {}).get("name", "unknown")

    governance_note = ""
    if governance_result is not None:
        governance_note = f"\n\n**Governance:** blocked — {governance_result['reasoning']}"

    blame_note = _blame_context(client, repo, run, triage_result)

    body = (
        f"🤖 **Self-healing CI agent diagnosis**\n\n"
        f"**Category:** `{triage_result['category']}` (confidence "
        f"{triage_result['confidence']:.2f})\n\n"
        f"**Root cause:** {triage_result['root_cause']}\n\n"
        f"**Likely owner:** commit {run['head_sha'][:7]} by "
        f"{f'@{author_login}' if author_login else author_name}"
        f"{governance_note}{blame_note}\n\n"
        f"---\n_This category is not auto-fixed by design — it requires understanding "
        f"business intent. See [run #{run['id']}]({run['html_url']})._"
    )
    assignees = [author_login] if author_login else None
    return client.create_issue(
        repo,
        title=f"CI failure needs attention: {triage_result['category']} in run #{run['id']}",
        body=body,
        assignees=assignees,
    )
