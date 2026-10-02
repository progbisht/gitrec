from typing import List, Dict, Tuple
from gitrec.models.base import WorkItemModel, CommitModel, PullRequestModel, IssueModel, WorkType
from gitrec.engine.classifier import WorkClassifier


class ConfidenceScorer:
    """
    Computes holistic confidence scores based on:
    - Direct PR/Issue links (+0.25)
    - Conventional commit alignment (+0.20)
    - Labels / Milestones presence (+0.15)
    - Clean single-purpose commit graph (+0.10)
    - Clear semantic classification (+0.20)
    """

    def __init__(self, commits: List[CommitModel], prs: List[PullRequestModel], issues: List[IssueModel]):
        self.commits_map = {c.sha: c for c in commits}
        self.prs_map = {p.number: p for p in prs}
        self.issues_map = {i.number: i for i in issues}
        self.classifier = WorkClassifier()

    def process_and_score_items(self, items: List[WorkItemModel]) -> List[WorkItemModel]:
        scored_items = []
        for item in items:
            work_type, cls_conf, cls_reasons = self.classifier.classify(
                item, self.commits_map, self.prs_map, self.issues_map
            )

            score = 0.50  # Base score
            evidence = list(item.evidence)

            # Boost 1: PR association with clear title and multi-commits
            if item.pr_numbers:
                score += 0.28
                evidence.append(f"Linked to PR #{', #'.join(map(str, item.pr_numbers))} (+0.28)")

            # Boost 2: Issue association / closing links
            if item.issue_numbers:
                score += 0.15
                evidence.append(f"Linked to Issue #{', #'.join(map(str, item.issue_numbers))} (+0.15)")

            # Boost 3: Label confirmation
            if item.labels:
                score += 0.10
                evidence.append(f"Structured GitHub labels: {', '.join(item.labels)} (+0.10)")

            # Boost 4: Semantic classifier confidence
            if cls_conf >= 0.80 and work_type != WorkType.UNKNOWN:
                score += 0.15
                evidence.extend(cls_reasons[:3])
            elif work_type == WorkType.UNKNOWN:
                score -= 0.20
                evidence.append("Uncertain classification category (-0.20)")

            # Penalize single commit with vague message (e.g. "fix stuff", "wip", "update")
            if len(item.commit_shas) == 1 and not item.pr_numbers and not item.issue_numbers:
                sha = item.commit_shas[0]
                if sha in self.commits_map:
                    msg = self.commits_map[sha].message.strip()
                    if len(msg.split()) < 3 or msg.lower() in ["update", "wip", "misc", "changes", "fix", "fix stuff", "stuff"]:
                        score -= 0.25
                        evidence.append("Single commit with brief/vague message (-0.25)")


            final_confidence = max(0.10, min(1.0, round(score, 2)))

            # Update item attributes
            item.work_type = work_type
            item.confidence = final_confidence
            item.evidence = evidence
            scored_items.append(item)

        return scored_items
