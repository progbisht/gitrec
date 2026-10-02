import requests
import re
from typing import List, Optional, Dict, Any
from datetime import datetime
from gitrec.models.base import PullRequestModel, IssueModel


class GitHubExtractor:
    def __init__(self, owner: str, repo: str, token: Optional[str] = None):
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") and not token.startswith("token ") else token


    def _get_all_pages(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        results = []
        url = f"{self.base_url}/{endpoint}"
        p = params.copy() if params else {}
        p["per_page"] = 100
        p["page"] = 1
        
        while url:
            response = requests.get(url, headers=self.headers, params=p)
            if response.status_code == 404:
                return []
            if response.status_code != 200:
                response.raise_for_status()
            
            data = response.json()
            if not data:
                break
            
            results.extend(data)
            p["page"] += 1
            if len(data) < 100:
                break
        return results

    def _get_comments(self, comments_url: str) -> List[str]:
        comments = []
        try:
            resp = requests.get(comments_url, headers=self.headers, params={"per_page": 100}, timeout=10)
            if resp.status_code == 200:
                c_data = resp.json()
                if isinstance(c_data, list):
                    for item in c_data:
                        author = item.get("user", {}).get("login", "unknown")
                        body = item.get("body", "").strip()
                        if body:
                            comments.append(f"@{author}: {body}")
        except Exception:
            pass
        return comments

    def _enrich_single_pr(self, d: Dict[str, Any]) -> PullRequestModel:
        num = d.get("number")
        commit_shas = []
        changed_files = []
        try:
            c_resp = requests.get(f"{self.base_url}/pulls/{num}/commits", headers=self.headers, timeout=10)
            if c_resp.status_code == 200:
                c_json = c_resp.json()
                if isinstance(c_json, list):
                    commit_shas = [c["sha"] for c in c_json]
        except Exception:
            pass

        try:
            f_resp = requests.get(f"{self.base_url}/pulls/{num}/files", headers=self.headers, timeout=10)
            if f_resp.status_code == 200:
                f_json = f_resp.json()
                if isinstance(f_json, list):
                    changed_files = [f["filename"] for f in f_json if "filename" in f]
        except Exception:
            pass

        comments = self._get_comments(f"{self.base_url}/issues/{num}/comments")
        review_comments = self._get_comments(f"{self.base_url}/pulls/{num}/comments")
        all_comments = comments + [f"[Review] {rc}" for rc in review_comments]

        labels = [lbl["name"] for lbl in d.get("labels", [])]
        reviewers = [r["login"] for r in d.get("requested_reviewers", [])]

        return PullRequestModel(
            number=num,
            title=d.get("title", ""),
            body=d.get("body") or "",
            author=d.get("user", {}).get("login", "unknown"),
            state=d.get("state", "closed"),
            source_branch=d.get("head", {}).get("ref"),
            target_branch=d.get("base", {}).get("ref"),
            created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
            closed_at=datetime.fromisoformat(d["closed_at"].replace("Z", "+00:00")) if d.get("closed_at") else None,
            merged_at=datetime.fromisoformat(d["merged_at"].replace("Z", "+00:00")) if d.get("merged_at") else None,
            labels=labels,
            milestone=d.get("milestone", {}).get("title") if d.get("milestone") else None,
            reviewers=reviewers,
            commit_shas=commit_shas,
            changed_files=changed_files,
            comments=all_comments,
            html_url=d.get("html_url")
        )


    def extract_pull_requests(self, max_items: Optional[int] = None) -> List[PullRequestModel]:
        prs_data = self._get_all_pages("pulls", {"state": "all"})
        if max_items:
            prs_data = prs_data[:max_items]

        import concurrent.futures
        prs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            prs = list(executor.map(self._enrich_single_pr, prs_data))
        return prs

    def _enrich_single_issue(self, d: Dict[str, Any]) -> IssueModel:
        num = d.get("number")
        comments = []
        if d.get("comments", 0) > 0 and num:
            comments = self._get_comments(f"{self.base_url}/issues/{num}/comments")

        labels = [lbl["name"] for lbl in d.get("labels", [])]
        return IssueModel(
            number=num,
            title=d.get("title", ""),
            body=d.get("body") or "",
            author=d.get("user", {}).get("login", "unknown"),
            state=d.get("state", "closed"),
            created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
            closed_at=datetime.fromisoformat(d["closed_at"].replace("Z", "+00:00")) if d.get("closed_at") else None,
            labels=labels,
            milestone=d.get("milestone", {}).get("title") if d.get("milestone") else None,
            comments_count=d.get("comments", 0),
            comments=comments,
            html_url=d.get("html_url")
        )

    def extract_issues(self, max_items: Optional[int] = None) -> List[IssueModel]:
        issues_data = self._get_all_pages("issues", {"state": "all"})
        issues_data = [d for d in issues_data if "pull_request" not in d]
        if max_items:
            issues_data = issues_data[:max_items]

        import concurrent.futures
        issues = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            issues = list(executor.map(self._enrich_single_issue, issues_data))
        return issues

