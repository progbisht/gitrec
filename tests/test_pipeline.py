import pytest
from datetime import datetime, timedelta
from gitrec.models.base import CommitModel, PullRequestModel, IssueModel, WorkType, WorkItemStatus, KanbanStatus
from gitrec.engine.grouper import WorkGrouper
from gitrec.engine.classifier import WorkClassifier
from gitrec.engine.scorer import ConfidenceScorer
from gitrec.storage.db import Storage
from gitrec.jira.migrator import JiraMigrator


def test_work_grouping_explicit_links():
    # 1 PR with 2 commits linked to 1 Issue
    c1 = CommitModel(
        sha="c111", short_sha="c111", message="feat(auth): add login endpoint",
        author_name="Alice", author_email="alice@test.com", timestamp=datetime(2026, 1, 1, 10, 0),
        changed_files=["src/auth/login.py"]
    )
    c2 = CommitModel(
        sha="c222", short_sha="c222", message="test(auth): add unit test for login",
        author_name="Alice", author_email="alice@test.com", timestamp=datetime(2026, 1, 1, 11, 0),
        changed_files=["tests/test_login.py"]
    )
    pr = PullRequestModel(
        number=101, title="feat(auth): implement user authentication",
        body="Closes #42", author="alice", state="merged",
        created_at=datetime(2026, 1, 1, 12, 0), commit_shas=["c111", "c222"]
    )
    issue = IssueModel(
        number=42, title="User Authentication Requirement",
        author="bob", state="closed", created_at=datetime(2026, 1, 1, 8, 0),
        labels=["feature"]
    )

    grouper = WorkGrouper([c1, c2], [pr], [issue])
    work_items = grouper.group_work()

    assert len(work_items) == 1
    item = work_items[0]
    assert item.issue_numbers == [42]
    assert item.pr_numbers == [101]
    assert set(item.commit_shas) == {"c111", "c222"}
    assert item.kanban_status == KanbanStatus.DONE

    scorer = ConfidenceScorer([c1, c2], [pr], [issue])
    scored = scorer.process_and_score_items(work_items)
    assert scored[0].work_type == WorkType.FEATURE
    assert scored[0].confidence >= 0.90


def test_kanban_statuses_inference():
    # 1. Open Issue (Untriaged) -> Backlog
    iss_backlog = IssueModel(
        number=1, title="Idea for Dark Mode", author="user1", state="open",
        created_at=datetime(2026, 1, 1, 10, 0)
    )
    items1 = WorkGrouper([], [], [iss_backlog]).group_work()
    assert items1[0].kanban_status == KanbanStatus.BACKLOG

    # 2. Open Issue (Triaged/Milestoned) -> Ready For Development
    iss_ready = IssueModel(
        number=2, title="Add Webhook Support", author="user2", state="open",
        created_at=datetime(2026, 1, 1, 10, 0), labels=["ready", "help wanted"]
    )
    items2 = WorkGrouper([], [], [iss_ready]).group_work()
    assert items2[0].kanban_status == KanbanStatus.READY_FOR_DEV

    # 3. Open PR -> In Progress
    pr_open = PullRequestModel(
        number=10, title="WIP: Webhook implementation", author="dev1", state="open",
        created_at=datetime(2026, 1, 2, 10, 0)
    )
    items3 = WorkGrouper([], [pr_open], []).group_work()
    assert items3[0].kanban_status == KanbanStatus.IN_PROGRESS


def test_classifier_bug_detection():
    classifier = WorkClassifier()
    c = CommitModel(
        sha="b111", short_sha="b111", message="fix(payment): resolve null pointer crash on checkout",
        author_name="Bob", author_email="bob@test.com", timestamp=datetime(2026, 1, 2, 10, 0),
        changed_files=["src/payment.py"]
    )
    w_type, conf, reasons = classifier.classify(
        from_commit(c), {c.sha: c}, {}, {}
    )
    assert w_type == WorkType.BUG


def from_commit(c: CommitModel):
    return WorkGrouper([c], [], []).group_work()[0]


def test_storage_and_idempotent_migration(tmp_path):
    db_file = str(tmp_path / "test.db")
    storage = Storage(db_file)

    c = CommitModel(
        sha="s111", short_sha="s111", message="docs: update readme",
        author_name="Charlie", author_email="charlie@test.com", timestamp=datetime(2026, 1, 3, 10, 0),
        changed_files=["README.md"]
    )
    storage.save_commits([c])
    assert len(storage.get_commits()) == 1

    grouper = WorkGrouper([c], [], [])
    items = grouper.group_work()
    storage.save_work_items(items)
    
    # Reload from DB and verify KanbanStatus
    loaded = storage.get_work_items()
    assert len(loaded) == 1
    assert loaded[0].kanban_status == KanbanStatus.DONE

    # Dry run migration
    migrator = JiraMigrator(None, storage, project_key="TEST", dry_run=True)
    res = migrator.migrate(items)
    assert len(res) == 1
    assert res[0]["status"] == "dry-run-create"
    assert res[0]["kanban_status"] == "Done"

