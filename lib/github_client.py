"""Thin GitHub REST API wrapper used against *watched* repos.

Authenticates with WATCHED_REPOS_PAT — a fine-grained PAT scoped only to the
repos this agent watches (Contents: write, Pull requests: write, Issues:
write, Actions: read). Never used against this agent's own repo; that uses
the Actions-provided GITHUB_TOKEN directly via git/gh in the workflow.
"""
import base64
import os

import requests

API_ROOT = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ["WATCHED_REPOS_PAT"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _get(self, path: str, **kwargs):
        resp = self.session.get(f"{API_ROOT}{path}", timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, json: dict):
        resp = self.session.post(f"{API_ROOT}{path}", json=json, timeout=30)
        resp.raise_for_status()
        return resp

    def _put(self, path: str, json: dict):
        resp = self.session.put(f"{API_ROOT}{path}", json=json, timeout=30)
        resp.raise_for_status()
        return resp

    # --- workflow runs -----------------------------------------------

    def list_recent_runs(self, repo: str, per_page: int = 20) -> list[dict]:
        resp = self._get(f"/repos/{repo}/actions/runs", params={"per_page": per_page})
        return resp.json()["workflow_runs"]

    def get_run_log_text(self, repo: str, run_id: int) -> str:
        """Concatenates the logs of every job in the run (plain text)."""
        jobs = self._get(f"/repos/{repo}/actions/runs/{run_id}/jobs").json()["jobs"]
        chunks = []
        for job in jobs:
            log_resp = self.session.get(
                f"{API_ROOT}/repos/{repo}/actions/jobs/{job['id']}/logs", timeout=30
            )
            if log_resp.ok:
                chunks.append(f"=== job: {job['name']} ===\n{log_resp.text}")
        return "\n\n".join(chunks)

    # --- commits / diffs ----------------------------------------------

    def get_commit(self, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{repo}/commits/{sha}").json()

    def compare_commits(self, repo: str, base: str, head: str) -> dict:
        return self._get(f"/repos/{repo}/compare/{base}...{head}").json()

    def get_file(self, repo: str, path: str, ref: str) -> dict:
        """Returns {"content": <decoded text>, "sha": <blob sha>}."""
        data = self._get(f"/repos/{repo}/contents/{path}", params={"ref": ref}).json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return {"content": content, "sha": data["sha"]}

    def last_commit_touching_path(self, repo: str, path: str, before_sha: str) -> dict | None:
        """File-level approximation of blame: most recent commit that
        touched `path`, as of `before_sha`. Best-effort context only."""
        resp = self._get(
            f"/repos/{repo}/commits",
            params={"path": path, "sha": before_sha, "per_page": 1},
        )
        commits = resp.json()
        return commits[0] if commits else None

    # --- writes ---------------------------------------------------------

    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        self._post(f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": from_sha})

    def update_file(self, repo: str, path: str, message: str, content: str, branch: str, sha: str) -> None:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        self._put(
            f"/repos/{repo}/contents/{path}",
            {"message": message, "content": encoded, "branch": branch, "sha": sha},
        )

    def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str = "main") -> dict:
        return self._post(
            f"/repos/{repo}/pulls", {"title": title, "body": body, "head": head, "base": base}
        ).json()

    def create_issue(self, repo: str, title: str, body: str, assignees: list[str] | None = None) -> dict:
        payload = {"title": title, "body": body}
        if assignees:
            payload["assignees"] = assignees
        return self._post(f"/repos/{repo}/issues", payload).json()

    def create_commit_comment(self, repo: str, sha: str, body: str) -> dict:
        return self._post(f"/repos/{repo}/commits/{sha}/comments", {"body": body}).json()
