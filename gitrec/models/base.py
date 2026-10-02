from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class WorkType(str, Enum):
    EPIC = "Epic"
    FEATURE = "Feature"
    BUG = "Bug"
    TASK = "Task"
    IMPROVEMENT = "Improvement"
    REFACTOR = "Refactor"
    PERFORMANCE = "Performance"
    SECURITY = "Security"
    INFRASTRUCTURE = "Infrastructure"
    DOCUMENTATION = "Documentation"
    TEST = "Test"
    CHORE = "Chore"
    CONFIGURATION = "Configuration"
    DEPENDENCY = "Dependency"
    TECHNICAL_DEBT = "Technical Debt"
    MAINTENANCE = "Maintenance"
    SUB_TASK = "Sub-task"
    UNKNOWN = "Unknown"




class CommitModel(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committer_name: Optional[str] = None
    committer_email: Optional[str] = None
    timestamp: datetime
    parents: List[str] = Field(default_factory=list)
    branch: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    is_merge: bool = False


class PullRequestModel(BaseModel):
    number: int
    title: str
    body: Optional[str] = ""
    author: str
    state: str  # open, closed, merged
    source_branch: Optional[str] = None
    target_branch: Optional[str] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    merged_at: Optional[datetime] = None
    labels: List[str] = Field(default_factory=list)
    milestone: Optional[str] = None
    reviewers: List[str] = Field(default_factory=list)
    commit_shas: List[str] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    comments: List[str] = Field(default_factory=list)
    html_url: Optional[str] = None



class IssueModel(BaseModel):
    number: int
    title: str
    body: Optional[str] = ""
    author: str
    state: str  # open, closed
    created_at: datetime
    closed_at: Optional[datetime] = None
    labels: List[str] = Field(default_factory=list)
    milestone: Optional[str] = None
    comments_count: int = 0
    comments: List[str] = Field(default_factory=list)
    html_url: Optional[str] = None


class WorkItemStatus(str, Enum):
    INFERRED = "Inferred"
    REVIEWED = "Reviewed"
    APPROVED = "Approved"
    EXCLUDED = "Excluded"
    MIGRATED = "Migrated"


class KanbanStatus(str, Enum):
    BACKLOG = "Backlog"
    READY_FOR_DEV = "Ready For Development"
    IN_PROGRESS = "In Progress"
    DONE = "Done"


class WorkItemModel(BaseModel):
    id: str  # e.g. H001
    title: str
    description: Optional[str] = ""
    work_type: WorkType = WorkType.UNKNOWN
    confidence: float = 0.0
    evidence: List[str] = Field(default_factory=list)
    status: WorkItemStatus = WorkItemStatus.INFERRED
    kanban_status: KanbanStatus = KanbanStatus.DONE
    
    # Hierarchy
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    
    commit_shas: List[str] = Field(default_factory=list)
    pr_numbers: List[int] = Field(default_factory=list)
    issue_numbers: List[int] = Field(default_factory=list)
    
    authors: List[str] = Field(default_factory=list)
    first_activity: datetime
    last_activity: datetime
    affected_files: List[str] = Field(default_factory=list)
    affected_modules: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    
    jira_key: Optional[str] = None
    jira_issue_type: Optional[str] = None
    jira_status: Optional[str] = None
    custom_notes: Optional[str] = None

