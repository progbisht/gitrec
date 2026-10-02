import re
from typing import List, Tuple, Dict, Any
from gitrec.models.base import WorkType, WorkItemModel, CommitModel, PullRequestModel, IssueModel


class WorkClassifier:
    """
    Classifies work items into one of the controlled categories:
    - Feature
    - Bug
    - Improvement
    - Refactor
    - Performance
    - Security
    - Infrastructure
    - Documentation
    - Test
    - Maintenance
    - Unknown / Needs Review
    """

    # Keyword / regex rules
    RULES = [
        (WorkType.SECURITY, [
            r"\b(security|cve|vulnerability|auth|sanitize|xss|csrf|token|secret|encryption|leak)\b"
        ]),
        (WorkType.BUG, [
            r"^(fix|hotfix|bugfix)(\([^)]+\))?:",
            r"\b(fix|fixed|fixes|bug|error|exception|crash|broken|fault|issue|regression|patch|jwt expiration|jwt)\b"
        ]),
        (WorkType.DEPENDENCY, [
            r"^(deps|dependency)(\([^)]+\))?:",
            r"\b(upgrade|bump|dependencies|dependency|spring boot|npm|pip|cargo|go\.mod|gemfile)\b"
        ]),
        (WorkType.PERFORMANCE, [
            r"^(perf|performance)(\([^)]+\))?:",
            r"\b(perf|performance|optimize|speed|slow|latency|throughput|cache|memory leak|bottleneck)\b"
        ]),
        (WorkType.DOCUMENTATION, [
            r"^(docs|doc)(\([^)]+\))?:",
            r"\b(readme|doc|docs|documentation|changelog|manual|guide|license|comments)\b"
        ]),
        (WorkType.TEST, [
            r"^(test|tests)(\([^)]+\))?:",
            r"\b(add unit tests?|unit tests?|integration tests?|test|tests|testing|mock|coverage|pytest|jest)\b"
        ]),

        (WorkType.REFACTOR, [
            r"^(refactor)(\([^)]+\))?:",
            r"\b(refactor|clean|cleanup|restructure|reorganize|rename|modularize|simplify|service)\b"
        ]),
        (WorkType.CONFIGURATION, [
            r"^(config|conf)(\([^)]+\))?:",
            r"\b(config|configuration|settings|env|environment|\.env|properties|yaml|toml|ini)\b"
        ]),
        (WorkType.INFRASTRUCTURE, [
            r"^(ci|build|infra|cd)(\([^)]+\))?:",
            r"\b(docker|dockerfile|docker compose|compose|k8s|kubernetes|helm|terraform|pipeline|github action|workflow|travis|jenkins|deploy)\b"
        ]),
        (WorkType.CHORE, [
            r"^(chore)(\([^)]+\))?:",
            r"\b(chore|formatting|lint|prettier|style|whitespace)\b"
        ]),
        (WorkType.MAINTENANCE, [
            r"^(maint|maintenance)(\([^)]+\))?:",
            r"\b(maintenance|housekeeping)\b"
        ]),
        (WorkType.FEATURE, [
            r"^(feat|feature)(\([^)]+\))?:",
            r"\b(feat|feature|implement|introduced|new feature|support|provide|allow|create|oauth|oauth login|login|adds? (?:feature|endpoint|support|option|capability|view|page|button|screen|model))\b",
            r"\b(add|added)\b"
        ]),


    ]

    LABEL_MAPPING = {
        "epic": WorkType.EPIC,
        "feature-request": WorkType.FEATURE,
        "feature": WorkType.FEATURE,
        "bug": WorkType.BUG,
        "fix": WorkType.BUG,
        "security": WorkType.SECURITY,
        "enhancement": WorkType.FEATURE,
        "documentation": WorkType.DOCUMENTATION,
        "docs": WorkType.DOCUMENTATION,
        "refactor": WorkType.REFACTOR,
        "performance": WorkType.PERFORMANCE,
        "perf": WorkType.PERFORMANCE,
        "test": WorkType.TEST,
        "testing": WorkType.TEST,
        "chore": WorkType.CHORE,
        "config": WorkType.CONFIGURATION,
        "configuration": WorkType.CONFIGURATION,
        "infra": WorkType.INFRASTRUCTURE,
        "infrastructure": WorkType.INFRASTRUCTURE,
        "ci": WorkType.INFRASTRUCTURE,
        "dependencies": WorkType.DEPENDENCY,
        "dependency": WorkType.DEPENDENCY,
        "maintenance": WorkType.MAINTENANCE
    }


    def classify(self, item: WorkItemModel, commits: Dict[str, CommitModel], prs: Dict[int, PullRequestModel], issues: Dict[int, IssueModel]) -> Tuple[WorkType, float, List[str]]:
        reasons = []
        scores: Dict[WorkType, float] = {wt: 0.0 for wt in WorkType}

        # 1. Labels from PRs / Issues (strongest signal)
        for label in item.labels:
            norm_label = label.lower().strip()
            for key, w_type in self.LABEL_MAPPING.items():
                if key in norm_label:
                    scores[w_type] += 1.5
                    reasons.append(f"Label '{label}' matches {w_type.value}")

        # 2. Inspect PR / Issue titles and bodies
        texts_to_check = [item.title, item.description]
        for pr_num in item.pr_numbers:
            if pr_num in prs:
                texts_to_check.append(prs[pr_num].title)
        for iss_num in item.issue_numbers:
            if iss_num in issues:
                texts_to_check.append(issues[iss_num].title)

        # 3. Inspect commit messages
        for sha in item.commit_shas:
            if sha in commits:
                texts_to_check.append(commits[sha].message)

        # Apply regex rules
        for text in texts_to_check:
            if not text:
                continue
            first_line = text.strip().splitlines()[0] if text.strip() else ""
            
            for w_type, patterns in self.RULES:
                for pattern in patterns:
                    # Conventional commit match at start of line
                    if pattern.startswith("^"):
                        if re.search(pattern, first_line, re.IGNORECASE):
                            scores[w_type] += 1.2
                            reasons.append(f"Conventional prefix match for {w_type.value} in '{first_line[:40]}...'")
                    else:
                        # Keyword match
                        matches = re.findall(pattern, text, re.IGNORECASE)
                        if matches:
                            # Higher weight for specific / compound matches vs generic single verbs
                            is_generic_verb = pattern == r"\b(add|added)\b"
                            weight = (min(len(matches) * 0.15, 0.3)) if is_generic_verb else (min(len(matches) * 0.4, 1.2))
                            scores[w_type] += weight
                            reasons.append(f"Keyword match for {w_type.value} ({', '.join(set(matches[:3]))})")


        # 4. File-based heuristics
        has_tests_only = bool(item.affected_files and all("test" in f.lower() or "spec" in f.lower() for f in item.affected_files))
        has_docs_only = bool(item.affected_files and all(f.lower().endswith((".md", ".rst", ".txt", ".adoc")) or "doc" in f.lower() for f in item.affected_files))
        has_infra_only = bool(item.affected_files and all(f.lower().endswith((".yml", ".yaml", ".dockerfile", "dockerfile", ".tf", ".sh")) or ".github" in f.lower() for f in item.affected_files))

        if has_tests_only:
            scores[WorkType.TEST] += 1.0
            reasons.append("All changed files are test files")
        elif has_docs_only:
            scores[WorkType.DOCUMENTATION] += 1.0
            reasons.append("All changed files are documentation files")
        elif has_infra_only:
            scores[WorkType.INFRASTRUCTURE] += 1.0
            reasons.append("All changed files are CI/infra config files")

        # Pick top score
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_type, top_score = sorted_scores[0]

        if top_score <= 0.2:
            return WorkType.UNKNOWN, 0.30, ["Insufficient semantic signals to categorize"]

        # Calculate normalized confidence (0.50 to 1.00)
        confidence = min(0.50 + (top_score * 0.15), 1.0)
        return top_type, round(confidence, 2), reasons
