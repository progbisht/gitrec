import sqlite3
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from gitrec.models.base import CommitModel, PullRequestModel, IssueModel, WorkItemModel, WorkType, WorkItemStatus, KanbanStatus


class Storage:
    def __init__(self, db_path: str = "gitrec_store.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS commits (
                sha TEXT PRIMARY KEY,
                short_sha TEXT,
                message TEXT,
                author_name TEXT,
                author_email TEXT,
                committer_name TEXT,
                committer_email TEXT,
                timestamp TEXT,
                parents TEXT,
                branch TEXT,
                changed_files TEXT,
                insertions INTEGER,
                deletions INTEGER,
                is_merge INTEGER
            )
            """)
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pull_requests (
                number INTEGER PRIMARY KEY,
                title TEXT,
                body TEXT,
                author TEXT,
                state TEXT,
                source_branch TEXT,
                target_branch TEXT,
                created_at TEXT,
                closed_at TEXT,
                merged_at TEXT,
                labels TEXT,
                milestone TEXT,
                reviewers TEXT,
                commit_shas TEXT,
                changed_files TEXT,
                comments TEXT,
                html_url TEXT
            )
            """)


            cursor.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                number INTEGER PRIMARY KEY,
                title TEXT,
                body TEXT,
                author TEXT,
                state TEXT,
                created_at TEXT,
                closed_at TEXT,
                labels TEXT,
                milestone TEXT,
                comments_count INTEGER,
                comments TEXT,
                html_url TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_items (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                work_type TEXT,
                confidence REAL,
                evidence TEXT,
                status TEXT,
                kanban_status TEXT DEFAULT 'Done',
                parent_id TEXT,
                children_ids TEXT,
                commit_shas TEXT,
                pr_numbers TEXT,
                issue_numbers TEXT,
                authors TEXT,
                first_activity TEXT,
                last_activity TEXT,
                affected_files TEXT,
                affected_modules TEXT,
                labels TEXT,
                jira_key TEXT,
                jira_issue_type TEXT,
                jira_status TEXT,
                custom_notes TEXT
            )
            """)

            # Migrations: Ensure comments column exists
            cursor.execute("PRAGMA table_info(pull_requests)")
            pr_cols = [row["name"] for row in cursor.fetchall()]
            if "comments" not in pr_cols:
                cursor.execute("ALTER TABLE pull_requests ADD COLUMN comments TEXT DEFAULT '[]'")

            cursor.execute("PRAGMA table_info(issues)")
            iss_cols = [row["name"] for row in cursor.fetchall()]
            if "comments" not in iss_cols:
                cursor.execute("ALTER TABLE issues ADD COLUMN comments TEXT DEFAULT '[]'")

            # Migration: Ensure kanban_status, parent_id, children_ids columns exist in legacy work_items tables
            cursor.execute("PRAGMA table_info(work_items)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "kanban_status" not in columns:
                cursor.execute("ALTER TABLE work_items ADD COLUMN kanban_status TEXT DEFAULT 'Done'")
            if "parent_id" not in columns:
                cursor.execute("ALTER TABLE work_items ADD COLUMN parent_id TEXT")
            if "children_ids" not in columns:
                cursor.execute("ALTER TABLE work_items ADD COLUMN children_ids TEXT DEFAULT '[]'")
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jira_mappings (
                work_item_id TEXT PRIMARY KEY,
                jira_key TEXT,
                jira_id TEXT,
                issue_type TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            conn.commit()

    def save_commits(self, commits: List[CommitModel]):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for c in commits:
                cursor.execute("""
                INSERT OR REPLACE INTO commits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.sha, c.short_sha, c.message, c.author_name, c.author_email,
                    c.committer_name, c.committer_email, c.timestamp.isoformat(),
                    json.dumps(c.parents), c.branch, json.dumps(c.changed_files),
                    c.insertions, c.deletions, 1 if c.is_merge else 0
                ))
            conn.commit()

    def get_commits(self) -> List[CommitModel]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM commits ORDER BY timestamp ASC")
            rows = cursor.fetchall()
            commits = []
            for r in rows:
                commits.append(CommitModel(
                    sha=r["sha"],
                    short_sha=r["short_sha"],
                    message=r["message"],
                    author_name=r["author_name"],
                    author_email=r["author_email"],
                    committer_name=r["committer_name"],
                    committer_email=r["committer_email"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    parents=json.loads(r["parents"]) if r["parents"] else [],
                    branch=r["branch"],
                    changed_files=json.loads(r["changed_files"]) if r["changed_files"] else [],
                    insertions=r["insertions"],
                    deletions=r["deletions"],
                    is_merge=bool(r["is_merge"])
                ))
            return commits

    def save_pull_requests(self, prs: List[PullRequestModel]):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for pr in prs:
                cursor.execute("""
                INSERT OR REPLACE INTO pull_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pr.number, pr.title, pr.body, pr.author, pr.state,
                    pr.source_branch, pr.target_branch, pr.created_at.isoformat(),
                    pr.closed_at.isoformat() if pr.closed_at else None,
                    pr.merged_at.isoformat() if pr.merged_at else None,
                    json.dumps(pr.labels), pr.milestone, json.dumps(pr.reviewers),
                    json.dumps(pr.commit_shas), json.dumps(pr.changed_files),
                    json.dumps(pr.comments), pr.html_url
                ))
            conn.commit()

    def get_pull_requests(self) -> List[PullRequestModel]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pull_requests ORDER BY created_at ASC")
            rows = cursor.fetchall()
            prs = []
            for r in rows:
                prs.append(PullRequestModel(
                    number=r["number"],
                    title=r["title"],
                    body=r["body"] or "",
                    author=r["author"],
                    state=r["state"],
                    source_branch=r["source_branch"],
                    target_branch=r["target_branch"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    closed_at=datetime.fromisoformat(r["closed_at"]) if r["closed_at"] else None,
                    merged_at=datetime.fromisoformat(r["merged_at"]) if r["merged_at"] else None,
                    labels=json.loads(r["labels"]) if r["labels"] else [],
                    milestone=r["milestone"],
                    reviewers=json.loads(r["reviewers"]) if r["reviewers"] else [],
                    commit_shas=json.loads(r["commit_shas"]) if r["commit_shas"] else [],
                    changed_files=json.loads(r["changed_files"]) if ("changed_files" in r.keys() and r["changed_files"]) else [],
                    comments=json.loads(r["comments"]) if ("comments" in r.keys() and r["comments"]) else [],
                    html_url=r["html_url"]
                ))
            return prs


    def save_issues(self, issues: List[IssueModel]):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for iss in issues:
                cursor.execute("""
                INSERT OR REPLACE INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    iss.number, iss.title, iss.body, iss.author, iss.state,
                    iss.created_at.isoformat(),
                    iss.closed_at.isoformat() if iss.closed_at else None,
                    json.dumps(iss.labels), iss.milestone, iss.comments_count,
                    json.dumps(iss.comments), iss.html_url
                ))
            conn.commit()

    def get_issues(self) -> List[IssueModel]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM issues ORDER BY created_at ASC")
            rows = cursor.fetchall()
            issues = []
            for r in rows:
                issues.append(IssueModel(
                    number=r["number"],
                    title=r["title"],
                    body=r["body"] or "",
                    author=r["author"],
                    state=r["state"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    closed_at=datetime.fromisoformat(r["closed_at"]) if r["closed_at"] else None,
                    labels=json.loads(r["labels"]) if r["labels"] else [],
                    milestone=r["milestone"],
                    comments_count=r["comments_count"],
                    comments=json.loads(r["comments"]) if ("comments" in r.keys() and r["comments"]) else [],
                    html_url=r["html_url"]
                ))
            return issues

    def save_work_items(self, items: List[WorkItemModel]):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for item in items:
                cursor.execute("""
                INSERT OR REPLACE INTO work_items (
                    id, title, description, work_type, confidence, evidence,
                    status, kanban_status, parent_id, children_ids,
                    commit_shas, pr_numbers, issue_numbers,
                    authors, first_activity, last_activity, affected_files,
                    affected_modules, labels, jira_key, jira_issue_type,
                    jira_status, custom_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.id, item.title, item.description, item.work_type.value,
                    item.confidence, json.dumps(item.evidence), item.status.value,
                    item.kanban_status.value, item.parent_id, json.dumps(item.children_ids),
                    json.dumps(item.commit_shas), json.dumps(item.pr_numbers),
                    json.dumps(item.issue_numbers), json.dumps(item.authors),
                    item.first_activity.isoformat(), item.last_activity.isoformat(),
                    json.dumps(item.affected_files), json.dumps(item.affected_modules),
                    json.dumps(item.labels), item.jira_key, item.jira_issue_type,
                    item.jira_status, item.custom_notes
                ))
            conn.commit()

    def get_work_items(self) -> List[WorkItemModel]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM work_items ORDER BY first_activity ASC")
            rows = cursor.fetchall()
            items = []
            for r in rows:
                k_status_val = r["kanban_status"] if "kanban_status" in r.keys() and r["kanban_status"] else "Done"
                try:
                    kanban_status = KanbanStatus(k_status_val)
                except ValueError:
                    kanban_status = KanbanStatus.DONE

                try:
                    w_type = WorkType(r["work_type"])
                except ValueError:
                    w_type = WorkType.UNKNOWN

                parent_id = r["parent_id"] if "parent_id" in r.keys() else None
                children_ids = json.loads(r["children_ids"]) if ("children_ids" in r.keys() and r["children_ids"]) else []

                items.append(WorkItemModel(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"] or "",
                    work_type=w_type,
                    confidence=r["confidence"],
                    evidence=json.loads(r["evidence"]) if r["evidence"] else [],
                    status=WorkItemStatus(r["status"]),
                    kanban_status=kanban_status,
                    parent_id=parent_id,
                    children_ids=children_ids,
                    commit_shas=json.loads(r["commit_shas"]) if r["commit_shas"] else [],
                    pr_numbers=json.loads(r["pr_numbers"]) if r["pr_numbers"] else [],
                    issue_numbers=json.loads(r["issue_numbers"]) if r["issue_numbers"] else [],
                    authors=json.loads(r["authors"]) if r["authors"] else [],
                    first_activity=datetime.fromisoformat(r["first_activity"]),
                    last_activity=datetime.fromisoformat(r["last_activity"]),
                    affected_files=json.loads(r["affected_files"]) if r["affected_files"] else [],
                    affected_modules=json.loads(r["affected_modules"]) if r["affected_modules"] else [],
                    labels=json.loads(r["labels"]) if r["labels"] else [],
                    jira_key=r["jira_key"],
                    jira_issue_type=r["jira_issue_type"],
                    jira_status=r["jira_status"],
                    custom_notes=r["custom_notes"]
                ))
            return items

    def update_work_item(self, item: WorkItemModel):
        self.save_work_items([item])

    def save_jira_mapping(self, work_item_id: str, jira_key: str, jira_id: str, issue_type: str, status: str):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            cursor.execute("""
            INSERT OR REPLACE INTO jira_mappings VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (work_item_id, jira_key, jira_id, issue_type, status, now, now))
            conn.commit()

    def get_jira_mappings(self) -> Dict[str, Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jira_mappings")
            rows = cursor.fetchall()
            return {r["work_item_id"]: dict(r) for r in rows}
