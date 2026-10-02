import re
from typing import List, Dict, Set, Tuple, Any
from gitrec.models.base import CommitModel, PullRequestModel, IssueModel


class RelationshipEngine:
    """
    Extracts explicit and implicit links between Commits, Pull Requests, and Issues.
    Evidence hierarchy:
    1. Commit -> PR direct inclusion
    2. PR -> Issue closing keywords / explicit #num references
    3. Commit -> Issue explicit #num references in commit messages
    4. Issue/Ticket keys in branch names
    5. Conventional commit scope & Module directory overlap
    6. Author + Temporal proximity
    """

    CLOSING_KEYWORDS = [
        r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)",
        r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+https?://github\.com/[^/]+/[^/]+/issues/(\d+)"
    ]
    
    ISSUE_REF_PATTERN = r"#(\d+)"
    JIRA_KEY_PATTERN = r"([A-Z][A-Z0-9]+-\d+)"
    BRANCH_TOPIC_PATTERN = r"(?:feature|feat|bugfix|fix|hotfix|chore|refactor)/([a-zA-Z0-9_-]+)"

    def __init__(self, commits: List[CommitModel], prs: List[PullRequestModel], issues: List[IssueModel]):
        self.commits = {c.sha: c for c in commits}
        self.prs = {p.number: p for p in prs}
        self.issues = {i.number: i for i in issues}

    def detect_links(self) -> List[Dict[str, Any]]:
        links = []

        # 1. Commit -> PR (from PR commit_shas)
        for pr in self.prs.values():
            for sha in pr.commit_shas:
                if sha in self.commits:
                    links.append({
                        "source": f"commit:{sha}",
                        "target": f"pr:{pr.number}",
                        "type": "pr_contains_commit",
                        "weight": 1.0,
                        "evidence": f"Commit {sha[:7]} is included in PR #{pr.number}"
                    })

        # 2. PR -> Issue links (Closing keywords & Issue refs)
        for pr in self.prs.values():
            text = f"{pr.title} {pr.body}"
            # Closing keywords
            for kw in self.CLOSING_KEYWORDS:
                for match in re.finditer(kw, text, re.IGNORECASE):
                    issue_num = int(match.group(1))
                    links.append({
                        "source": f"pr:{pr.number}",
                        "target": f"issue:{issue_num}",
                        "type": "pr_closes_issue",
                        "weight": 1.0,
                        "evidence": f"PR #{pr.number} closes Issue #{issue_num}"
                    })
            
            # Mentioned issues
            for match in re.finditer(self.ISSUE_REF_PATTERN, text):
                issue_num = int(match.group(1))
                if issue_num in self.issues and not any(l["target"] == f"issue:{issue_num}" and l["source"] == f"pr:{pr.number}" for l in links):
                    links.append({
                        "source": f"pr:{pr.number}",
                        "target": f"issue:{issue_num}",
                        "type": "pr_references_issue",
                        "weight": 0.85,
                        "evidence": f"PR #{pr.number} references Issue #{issue_num}"
                    })

        # 3. Commit -> Issue links (Commit messages referencing #issue or Jira key)
        for commit in self.commits.values():
            text = commit.message
            for kw in self.CLOSING_KEYWORDS:
                for match in re.finditer(kw, text, re.IGNORECASE):
                    issue_num = int(match.group(1))
                    links.append({
                        "source": f"commit:{commit.sha}",
                        "target": f"issue:{issue_num}",
                        "type": "commit_closes_issue",
                        "weight": 0.95,
                        "evidence": f"Commit {commit.short_sha} closing keyword references Issue #{issue_num}"
                    })
            for match in re.finditer(self.ISSUE_REF_PATTERN, text):
                issue_num = int(match.group(1))
                if issue_num in self.issues:
                    links.append({
                        "source": f"commit:{commit.sha}",
                        "target": f"issue:{issue_num}",
                        "type": "commit_references_issue",
                        "weight": 0.8,
                        "evidence": f"Commit {commit.short_sha} references Issue #{issue_num}"
                    })
            
        # 4. PR / Issue Epic-to-subtask & tracking hierarchy
        # Detect tracking checklists e.g. "- [ ] #123" or "- [x] #123" or "Epic: #123"
        checklist_pattern = r"(?:-\s*\[[ xX]\]\s*#(\d+)|(?:parent|epic|tracks|subtasks?):\s*#(\d+))"
        for issue in self.issues.values():
            text = f"{issue.title}\n{issue.body or ''}"
            for match in re.finditer(checklist_pattern, text, re.IGNORECASE):
                sub_num = int(match.group(1) or match.group(2))
                if sub_num in self.issues:
                    links.append({
                        "source": f"issue:{sub_num}",
                        "target": f"issue:{issue.number}",
                        "type": "issue_child_of_issue",
                        "weight": 1.0,
                        "evidence": f"Issue #{sub_num} is listed as a sub-task / tracked item of Issue #{issue.number}"
                    })
                elif sub_num in self.prs:
                    links.append({
                        "source": f"pr:{sub_num}",
                        "target": f"issue:{issue.number}",
                        "type": "pr_child_of_issue",
                        "weight": 1.0,
                        "evidence": f"PR #{sub_num} is tracked under parent Issue #{issue.number}"
                    })

        # 5. PR to PR branch hierarchy (e.g. PR target branch is another feature branch rather than main/master)
        for pr in self.prs.values():
            target_branch = pr.target_branch or ""
            if target_branch and target_branch not in ["main", "master", "develop", "release", "trunk"]:
                # Look for parent PR whose source branch is this target branch
                for parent_pr in self.prs.values():
                    if parent_pr.source_branch == target_branch:
                        links.append({
                            "source": f"pr:{pr.number}",
                            "target": f"pr:{parent_pr.number}",
                            "type": "pr_child_of_pr",
                            "weight": 1.0,
                            "evidence": f"PR #{pr.number} merges into feature branch '{target_branch}' of PR #{parent_pr.number}"
                        })
                        break

        return links
