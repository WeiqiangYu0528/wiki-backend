"""Git workflow for approval-gated documentation changes.

Operates on a separate publish repo (e.g. LLM_Knowledge_Base).
Creates branches, syncs workspace docs, commits, pushes, and creates PRs.
"""

import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

import httpx

from proposals import ALLOWED_PATH_PREFIX, Proposal


class GitWorkflowError(Exception):
    pass


class GitWorkflow:
    def __init__(
        self,
        workspace_dir: str,
        publish_dir: str,
        github_token: str = "",
        publish_repo: str = "",
    ) -> None:
        self.workspace_dir = workspace_dir
        self.publish_dir = publish_dir
        self.github_token = github_token
        self.publish_repo = publish_repo

    def validate_paths(self, proposal: Proposal) -> None:
        """Ensure every file path starts with the allowed prefix."""
        for fc in proposal.files:
            if not fc.path.startswith(ALLOWED_PATH_PREFIX):
                raise GitWorkflowError(
                    f"Path '{fc.path}' is outside allowed prefix '{ALLOWED_PATH_PREFIX}'"
                )

    def write_files_to_workspace(self, proposal: Proposal) -> list[str]:
        """Write proposed content to the workspace docs/ directory."""
        written: list[str] = []
        for fc in proposal.files:
            target = os.path.join(self.workspace_dir, fc.path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(fc.proposed_content)
            written.append(fc.path)
        return written

    def create_branch(self, branch_name: str) -> None:
        """Create and check out a new branch in the publish repo from main."""
        self._git(["checkout", "main"])
        self._git(["pull", "origin", "main"], allow_fail=True)
        self._git(["checkout", "-b", branch_name])

    def sync_to_publish(self) -> None:
        """Rsync workspace docs/ into the publish repo's docs/ directory."""
        src = os.path.join(self.workspace_dir, "docs") + "/"
        dst = os.path.join(self.publish_dir, "docs") + "/"
        subprocess.run(["rsync", "-a", "--delete", src, dst], check=True)

    def commit_and_push(self, message: str, branch_name: str) -> str:
        """Stage docs/, commit, push, and return the commit SHA."""
        self._git(["add", "docs/"])
        self._git(["commit", "-m", message])
        sha = self._git(["rev-parse", "HEAD"]).strip()

        if self.github_token:
            cred_file = os.path.join(self.publish_dir, ".git", "publish-credentials")
            try:
                self._git(["config", "credential.helper", f"store --file={cred_file}"])
                cred_input = (
                    f"protocol=https\nhost=github.com\n"
                    f"username=x-access-token\npassword={self.github_token}\n\n"
                )
                subprocess.run(
                    ["git", "-C", self.publish_dir, "credential", "approve"],
                    input=cred_input, text=True, check=True,
                )
                self._git(["push", "origin", branch_name])
            finally:
                if os.path.exists(cred_file):
                    os.remove(cred_file)
        else:
            self._git(["push", "origin", branch_name])

        return sha

    def create_pull_request(self, branch_name: str, title: str, body: str) -> str:
        """Create a PR via the GitHub API. Returns the PR URL."""
        if not self.github_token or not self.publish_repo:
            return "(PR creation skipped — no GitHub token or repo configured)"

        url = f"https://api.github.com/repos/{self.publish_repo}/pulls"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
        }
        data = {"title": title, "body": body, "head": branch_name, "base": "main"}
        resp = httpx.post(url, json=data, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()["html_url"]

    def cleanup_branch(self) -> None:
        """Switch the publish repo back to main."""
        self._git(["checkout", "main"])

    def execute(self, proposal: Proposal) -> dict:
        """Run the full git workflow for an approved proposal.

        Returns a dict with branch, commit_sha, pr_url, and changed_files.
        """
        self.validate_paths(proposal)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch_name = f"docs/wiki-update-{timestamp}-{proposal.id}"

        changed_files = self.write_files_to_workspace(proposal)
        self.create_branch(branch_name)

        try:
            self.sync_to_publish()
            sha = self.commit_and_push(proposal.commit_message, branch_name)

            pr_body = f"## Summary\n\n{proposal.summary}\n\n## Changed Files\n\n"
            pr_body += "\n".join(f"- `{f}`" for f in changed_files)
            pr_url = self.create_pull_request(branch_name, proposal.commit_message, pr_body)
        finally:
            self.cleanup_branch()

        return {
            "branch": branch_name,
            "commit_sha": sha,
            "pr_url": pr_url,
            "changed_files": changed_files,
        }

    def _git(self, args: list[str], *, allow_fail: bool = False) -> str:
        """Run a git command in the publish repo directory."""
        res = subprocess.run(
            ["git", "-C", self.publish_dir, *args],
            capture_output=True, text=True,
        )
        if res.returncode != 0 and not allow_fail:
            raise GitWorkflowError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout
