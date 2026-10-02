import csv
import json
from typing import List
from gitrec.models.base import WorkItemModel


class ReviewExporter:
    @staticmethod
    def export_to_json(items: List[WorkItemModel], filepath: str = "work_items_review.json"):
        data = [item.model_dump(mode="json") for item in items]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def import_from_json(filepath: str = "work_items_review.json") -> List[WorkItemModel]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [WorkItemModel.model_validate(item) for item in data]

    @staticmethod
    def export_to_csv(items: List[WorkItemModel], filepath: str = "work_items_review.csv"):
        fieldnames = [
            "id", "title", "work_type", "kanban_status", "confidence", "status",
            "commits_count", "commit_shas", "prs", "issues",
            "authors", "affected_modules", "first_activity", "last_activity",
            "jira_key", "custom_notes", "evidence"
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                writer.writerow({
                    "id": item.id,
                    "title": item.title,
                    "work_type": item.work_type.value,
                    "kanban_status": item.kanban_status.value,
                    "confidence": f"{item.confidence:.2f}",
                    "status": item.status.value,
                    "commits_count": len(item.commit_shas),
                    "commit_shas": " ".join(item.commit_shas),
                    "prs": ", ".join(map(str, item.pr_numbers)),
                    "issues": ", ".join(map(str, item.issue_numbers)),
                    "authors": ", ".join(item.authors),
                    "affected_modules": ", ".join(item.affected_modules),
                    "first_activity": item.first_activity.isoformat(),
                    "last_activity": item.last_activity.isoformat(),
                    "jira_key": item.jira_key or "",
                    "custom_notes": item.custom_notes or "",
                    "evidence": " | ".join(item.evidence)
                })

